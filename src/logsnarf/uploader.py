#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=invalid-name
"""BigQuery uploader

A class that implements :twisted:`twisted.internet.interfaces.IConsumer` for
uploading logs to BigQuery.
"""
import codecs
import hashlib
import logging
import uuid
import datetime
import time

from googleapiclient import errors as gerrors
import simplejson as json
import pytz
from twisted.internet import abstract
from twisted.internet import task
from zope import interface
from twisted.internet import interfaces

from . import errors as lserrors


# noinspection PyProtectedMember
class BigQueryUploader(abstract._ConsumerMixin):
    interface.implements(interfaces.IConsumer)

    def __init__(self, schema_obj, svc, table_name_schema, reactor=None):
        """

        :param schema_obj: A BigQuery schema
        :type schema_obj: logsnarf.schema.Schema
        :param svc: a Bigquery service
        :type svc: logsnarf.service.BigQuery
        :param table_name_schema:
          format to create table names. see :doc:`configuration` for more
          details.
        :type table_name_schema: str
        :param reactor: twisted reactor
        :type reactor: :twisted:`twisted.internet.reactor`
        """
        if not reactor:
            from twisted.internet import reactor
        self.reactor = reactor
        self.log = logging.getLogger(self.__class__.__name__)
        self.default_tz = pytz.utc

        self.schema = schema_obj
        self.service = svc

        self.table_name_schema = table_name_schema
        self._batchsize = 250  # Max 500
        self._max_buffer = 1000

        # Not accurate, just cached so we don't call it for every line
        # a looping call is more efficient than adding if then else
        # logic and a memoize decorator/property.
        self.now = datetime.datetime.now(tz=self.default_tz)
        self._now_task = task.LoopingCall(self.__update_now)
        self._delay = 30
        self._linebuffer = []
        self._buf = ''
        self._upload_task = task.LoopingCall(self.upload)
        # ConsumerMixin
        self.connected = True
        self.disconnected = False
        self.disconnecting = False
        self.paused = False
        self.uploadq = {}
        self.max_upload_n = 30

    def __update_now(self):
        self.now = datetime.datetime.now(tz=self.default_tz)

    def setDefaultTZ(self, tz):
        """Set the default timezone

        :param tz: timezone to set as default
        :type tz: str or datetime.tzinfo
        """
        if isinstance(tz, datetime.tzinfo):
            self.default_tz = tz
        else:
            self.default_tz = pytz.timezone(tz)

    def setBatchSize(self, n):
        """Set the number of log entries to batch in an upload.

        This is both a maximum batch size, minimum batch size. Barring
        uploads that occur at an interval set by :py:meth:`~.setFlushInterval`

        :param n: size to set batchsize to
        :type n: int
        """
        if n > 500:
            raise ValueError('Batch size can not exceed 500')
        self._batchsize = n

    def setMaxBuffer(self, n):
        """Set the max buffer size for uploads.

        Once this is reached, the uploader will ask the producer to pause until
        the buffer is below this limit.

        :param n: max buffer size
        :type n: int
        """
        self._max_buffer = n

    def setFlushInterval(self, n):
        """Set the flush interval for the uploader.

        Uploads will occur at least every flush interval seconds, as long as
        there is anything to upload.

        :param n: flush interval
        :type n: int
        """
        self._delay = n

    def startWriting(self):
        """Required by _ConsumerMixin."""
        pass

    def start(self):
        """Start the uploader.

        Start periodic tasks, at a trigger to flush our buffer on system
        shutdown. Make sure the producer is set to produce.
        """
        self.log.info('Started')
        self.now = datetime.datetime.now(tz=self.default_tz)
        self.service.updateTableList()
        self._now_task.start(3600)

        self._upload_task.start(self._delay)
        # noinspection PyUnresolvedReferences
        self.reactor.addSystemEventTrigger('before', 'shutdown', self.flush)
        self.resumeConsuming()

    def registerProducer(self, producer, streaming):
        """:twisted:`twisted.internet.interfaces.IConsumer` method

        Registers a producer with the uploader.

        :param producer: a producer
        :type producer: :twisted:`twisted.internet.interfaces.IProducer`
        :param streaming: true if the producer is a streaming producer
        :type streaming: bool

        """
        if not streaming:
            raise NotImplementedError('Only streaming producers are supported.')
        super(BigQueryUploader, self).registerProducer(producer, streaming)
        self.start()

    def pauseConsuming(self):
        """Pause consuming, by pausing our producer."""
        if self.producer:
            self.producerPaused = True
            self.producer.pauseProducing()

    def resumeConsuming(self):
        """Resume consuming, by resuming our producer."""
        if self.disconnecting:
            return

        if self.producer:
            self.producerPaused = False
            self.producer.resumeProducing()

    def write(self, data):
        """:twisted:`twisted.internet.interfaces.IConsumer` method

        Process data and add it to our buffer. It's preferable, but not
        required that full log lines are taken here.

        :param data: text containing line separated JSON
        :type data: str
        """
        lines = self._buf + data
        lines = lines.split('\n')
        self._buf = lines.pop()
        json_objs = []
        for l in lines:
            try:
                json_objs.append(self.schema.loads(l))
            except (ValueError, lserrors.ValidationError):
                self.log.exception('Unable to decode line %s', l)
        self.addData(json_objs)

    def addData(self, data):
        """This expects valid dicts to upload."""
        if isinstance(data, dict):
            data = [data]
        for entry in data:
            insert_id = entry.pop('_sha1')
            if insert_id is None:
                insert_id = uuid.uuid4().get_hex()
            if 'table' in entry:
                table = entry.pop('table')
            else:
                t = entry.get('time')
                if t:
                    t = datetime.datetime.fromtimestamp(t, tz=self.default_tz)
                else:
                    t = self.now
                table = self.table_name_schema.format(
                    YEAR=t.year, MONTH=t.month, DAY=t.day)
            self._linebuffer.append(
                (table, {'insertId': insert_id, 'json': entry}))
        current_bufsize = len(self._linebuffer)
        if current_bufsize >= self._batchsize:
            self.upload()
        if current_bufsize >= self._max_buffer and not self.paused:
            self.pauseConsuming()

    def flush(self):
        """Flush our buffer."""
        self.pauseConsuming()
        self.disconnecting = True
        self.log.debug('Flushing buffer to bigquery')
        while self._linebuffer:
            self.log.debug('Calling upload(flush=True)')
            self.upload(flush=True)
        self.disconnected = True

    def upload(self, flush=False):
        """Potentially insert some table data.

        :param flush: if this is part of flushing our buffer
        :type flush: bool
        """

        if self.paused:
            self.log.debug('upload called while paused')
            return

        loglines = self._linebuffer[:self._batchsize]
        self._linebuffer = self._linebuffer[self._batchsize:]
        if not flush and len(self._linebuffer) < self._max_buffer and \
                self.producer.paused:
            self.resumeConsuming()
        by_table = {}
        for table, l in loglines:
            by_table.setdefault(table, []).append(l)

        for table in by_table:
            upload_id = uuid.uuid4().get_hex()

            if flush:  # we do things synchronously in flush mode
                result = self.service.insertAll_s(
                    table, self.schema.schema, by_table[table], upload_id)
                self._uploadCB(result, upload_id, table, by_table[table],
                               synchronous=True)
            else:
                result = self.service.insertAll(
                    table, self.schema.schema, by_table[table], upload_id)
                result.addCallback(
                    self._uploadCB, upload_id, table, by_table[table])
                result.addErrback(self._errback, upload_id, table, by_table[table])
                self.uploadq[upload_id] = time.time()
                if len(self.uploadq) > self.max_upload_n and not self.paused:
                    self.pauseConsuming()

    def _errback(self, failure, upload_id, table, data):
        logging.error(failure)
        if failure.check(gerrors.HttpError):
            if failure.value.status == 503:
                self.log.info('Retrying upload id %s', upload_id)
                table = data[0]
                d = self.service.insertAll(
                    table, self.schema.schema, data, upload_id)
                d.addCallback(self._uploadCB, upload_id, table, retry_lines)
                d.addErrback(self._errback, upload_id, table, data)
                return d

        logging.error('Removing failed upload from queue %s', upload_id)
        if upload_id in self.uploadq:
            del self.uploadq[upload_id]
        try:
            from logsnarf import config

            c = config.Config()
            with codecs.getwriter('utf-8')(
                    c.openDataFile('failed_loglines', 'ab'),
                    errors='ignore') as fail_log:
                json.dump(data, fail_log)
                fail_log.write('\n')
            self.log.debug('Failed loglines for upload_id: %s written to disk',
                           upload_id)
        except (ValueError, IOError):
            self.log.error('Failed saving failed loglines to file')

    def _uploadCB(self, result, upload_id, table, data, synchronous=False):
        """Callback handler for the upload to BigQuery.
        Here we need to handle any partial failures, by re-queueing the
        affected rows.

        Note that since we're using an insertId, as long as we resubmit
        within a few minutes, we could resubmit the whole batch, but that
        seems wasteful.

        :param result: the result from the insertAll call
        :type result: dict https://cloud.google.com/bigquery/docs/reference
        /v2/tabledata/insertAll#response
        :param upload_id: internal unique identifier for the upload
        :type upload_id: str
        :param table: BigQuery table name
        :type table: str
        :param data: the rows passed to the insertAll call
        :type data: list(dict)
        :param synchronous: If this was a synchronous insertAll call
        :type synchronous: bool
        :return: may return a deferred if parts of the insertAll are retried.
        :rvalue: defer.Deferred or None
        """

        self.log.info('Upload callback for upload id %s called', upload_id)

        if result.get('insertErrors', None):
            retry_lines = []
            for insert_error in result['insertErrors']:
                index = insert_error['index']
                for e in insert_error['errors']:
                    if e['reason'] in ['backendError', 'timeout']:
                        if index > len(data):
                            self.log.error('Given an index %d out of our data '
                                           'range %d, the error was %r', index,
                                           len(data), e)
                        else:
                            self.log.error(
                                "%s : %s", e, data[index]['json'])
                            retry_lines.append(data[index])
                    if e['reason'] == 'invalid':
                        self.log.error(
                            'Fatal insert error: %s for line %s removing from '
                            'batch for retry', e, data[index])
            self.log.info('Retrying %s lines from upload %s', len(retry_lines),
                          upload_id)
            if synchronous:
                self.log.warning('Adding %d lines from upload %s back into '
                                 'the queue. They will get a new upload_id',
                                 len(retry_lines), upload_id)
                self._linebuffer.extend([(table, l) for l in retry_lines])
                return
            else:
                d = self.service.insertAll(
                    table, self.schema.schema, retry_lines, upload_id)
                d.addCallback(self._uploadCB, upload_id, table, retry_lines)
                d.addErrback(self._errback, upload_id, table, retry_lines)
                return d

        if upload_id in self.uploadq:
            time_taken = time.time() - self.uploadq.pop(upload_id, 0)
        else:
            time_taken = -1.0
        if len(self.uploadq) < self.max_upload_n:
            self.resumeConsuming()
        self.log.info('Upload %s complete, and took %f seconds', upload_id,
                      time_taken)
        return
