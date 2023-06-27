#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=invalid-name
"""BigQuery service."""

import logging
import ssl
import sys
import threading
import time
import uuid

import httplib2
from googleapiclient import discovery, errors
from twisted.internet import threads, task
from twisted.python import failure

from . import errors as lserrors


class BigQueryService(object):
    """A fairly basic wrapper around the google BigQuery API.
    """

    def __init__(self, project_id, dataset, creds, reactor=None, debug=False):
        """

        :param project_id: Numeric project id
        :type project_id: int
        :param dataset: Dataset name
        :type dataset: str
        :param creds: oauth2 credentials
        :type creds: oauth2client.Credentials
        :param reactor: twisted reactor object
        :type reactor: :twisted:`twisted.internet.reactor`

        """
        self.debug = debug
        if not reactor:
            from twisted.internet import reactor
        self.reactor = reactor
        self.log = logging.getLogger(self.__class__.__name__)

        self.project = project_id
        self.dataset = dataset
        self.tables = {}
        self.creds = creds
        self.local = threading.local()

    @property
    def http(self):
        """Creates and authorizes a httplib2.Http() instance"""
        if not hasattr(self.local, 'http'):
            http = httplib2.Http(timeout=120)
            self.creds.authorize(http)
            self.local.http = http
        return self.local.http

    @property
    def service(self):
        """Creates a BigQuery service."""
        if not hasattr(self.local, 'service'):
            self.local.service = discovery.build(
                'bigquery', 'v2', http=self.http)
            if self.debug:
                self.local.service.debug = True
        return self.local.service

    def updateTableList(self):
        """Update our internal cache of tables."""
        tables = self.service.tables()
        new_table_dict = {}
        try:
            table_request = tables.list(projectId=self.project,
                                        datasetId=self.dataset)
            while table_request is not None:
                table_list = table_request.execute()
                if table_list:
                    new_table_dict.update(dict(
                        [(t['tableReference']['tableId'], True)
                         for t in table_list.get('tables', [])]
                    ))
                table_request = tables.list_next(table_request, table_list)

            self.tables.update(new_table_dict)
        except (errors.Error, ssl.SSLError):
            self.log.exception('Error while retrieving list of tables')

    def createTable(self, name, table_schema):
        """Create a BigQuery table

        :param name: name of the table to create
        :type name: str
        :param table_schema:
          a list of fields representing the schema for the new table
        :type table_schema: list
        :raises googleapiclient.errors.HttpError: if a HTTP error occurs
        :raises ssl.SSLError: if an SSL based error occurs
        """
        self.log.info('Attempting to create table %s', name)
        self.updateTableList()
        self.log.debug('Table list updated')
        if name in self.tables:
            self.log.info('Table %s already exists', name)
            return
        tables = self.service.tables()
        body = {
            'schema': {
                'fields': table_schema,
            },
            'tableReference': {
                'projectId': self.project,
                'datasetId': self.dataset,
                'tableId': name,
            },
        }
        try:
            tables.insert(
                projectId=self.project,
                datasetId=self.dataset,
                body=body).execute()
        except errors.HttpError as e:
            if e.resp['status'] != '409':
                self.log.exception('failed to insert table %s', name)
                self.log.debug(e.resp)
                raise
            else:
                logging.debug('Table already exists %s', name)
        self.tables[name] = True

    def insertAll(self, table, table_schema, data, upload_id=None):
        """Insert rows into a table. Create the table if necessary.

        This is typically called in the main thread.

        :param table: table to insert data to.
        :type table: str
        :param table_schema:
          list of fields, representing the table schema this can be ommitted
          if the table already exists.
        :type table_schema: list
        :param data: the rows to be intersted. usually a list of dicts.
        :type data: list(dict)
        :param upload_id:
          unique identifier for this upload, only used internally for logging.
          one is generated if not supplied
        :type upload_id: str
        :return: a deferred for the results, the form of which is described at 
                 https://cloud.google.com/bigquery/docs/reference/v2
                 /tabledata/insertAll#response
        :rtype: :twisted:`twisted.internet.Deferred`
        """
        upload_id = upload_id or uuid.uuid4().hex

        if table not in self.tables:
            self.log.info('Table does not yet exist %s', table)
            self.log.debug('Triggering upload line %s', data[0])

            d = threads.deferToThread(self.createTable, table, table_schema)
            # We need an extra argument for the result
            d.addCallback(
                lambda x, call, _table, _schema, _data, _id: call(_table, _schema, _data, _id),
                self.insertAll, table, table_schema, data,
                upload_id)
        else:
            self.log.info('Starting upload %s', upload_id)
            d = threads.deferToThread(self._doInsertAll, table, data)
            d.addErrback(self._errback, upload_id, table, table_schema, data)

        return d

    def _doInsertAll(self, table, data):
        """Work method for insertAll to do be called *inside* a worker thread.

        :param table: table to insert data to.
        :type table: str
        :param data: the rows to be intersted. usually a list of dicts.
        :type data: list(dict)
        :return: Results of the insert.
        :rtype:
          https://cloud.google.com/bigquery/docs/reference/v2/tabledata
          /insertAll#response
        """
        tabledata = self.service.tabledata()
        insert = tabledata.insertAll(
            projectId=self.project,
            datasetId=self.dataset,
            tableId=table,
            body={'rows': data})
        return insert.execute()

    def insertAll_s(self, table, table_schema, data, upload_id=None):
        """Synchronous version of :py:meth:`~.insertAll`.

        :param table: table to insert data to.
        :type table: str
        :param table_schema:
          list of fields, representing the table schema this can be ommitted
          if the table already exists.
        :type table_schema: list
        :param data: the rows to be intersted. usually a list of dicts.
        :type data: list(dict)
        :param upload_id:
          unique identifier for this upload, only used internally for logging.
          one is generated if not supplied
        :type upload_id: str
        :return: Results of the insert.
        :rtype:
          https://cloud.google.com/bigquery/docs/reference/v2/tabledata
          /insertAll#response
          
        """
        upload_id = upload_id or uuid.uuid4().hex

        if table not in self.tables:
            self.log.info('Table does not yet exist %s', table)
            self.log.debug('Triggering upload line %s', data[0])
            self.createTable(table, table_schema)

        tabledata = self.service.tabledata()
        insert = tabledata.insertAll(
            projectId=self.project,
            datasetId=self.dataset,
            tableId=table,
            body={'rows': data})

        retries = 5
        for n in range(1, retries + 1):
            try:
                self.log.debug('Synchronous insertAll try %d', n)
                value = insert.execute()
                self.log.debug('Synchronous insertAll success')
                return value
            except (errors.HttpError, ssl.SSLError):
                fail = failure.Failure(*sys.exc_info())
                (retry, delay) = self._handleErrors(fail)
                # Ugh.. This should, hopefully be rare
                if retry:
                    self.log.error(
                        'Retrying insertAll upload_id %s after a %s delay.',
                        upload_id, delay)
                    time.sleep(delay)
                else:
                    raise
        self.log.error('Ran out of attempts to run insertAll in synchronous '
                       'mode. Raising ServiceException')
        raise lserrors.ServiceError('Was unable to complete upload id %d '
                                    'after %d attempts', upload_id, retries)

    def _handleErrors(self, fail):
        """Handle whole-request errors.

        :return tuple(bool, int):
            Tuple containing True, delay if the request should be retried
            after delay seconds. False, if the original exception should be
            re-raised.
        """
        if fail.type == errors.HttpError:
            # Retry errors.
            if fail.value.resp.status in ['403', '500', '503', '504']:
                self.log.error(fail)
                return True, 5
            else:
                self.log.error('Unhandled status code %d',
                               fail.value.resp.status)
                self.log.debug(fail.value.resp)
        elif fail.type == ssl.SSLError:
            self.log.error(fail)
            return True, 0
        else:
            return False, 0

    def _errback(self, fail, upload_id, table, table_schema, data):
        """Error handler for _upload, in the case of a whole-request failure."""
        self.log.error('Error for upload id %s %s', upload_id, fail)
        self.log.debug(fail.printTraceback())
        (retry, delay) = self._handleErrors(fail)
        if retry:
            self.log.error('Retrying upload %s after a %s second delay',
                           upload_id, delay)
            d = task.deferLater(self.reactor, delay,
                                self.insertAll, table, table_schema, data,
                                upload_id)
            return d
        return fail
