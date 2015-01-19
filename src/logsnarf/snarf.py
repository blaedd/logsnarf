#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- test-case-name: logsnarf.test.test_snarf -*-
# pylint: disable=invalid-name

"""Log directory watcher and reader.

This class is responsible for watching a set of directories for updates
to files matching a specific pattern. When those updates happen, it reads
those changes and passes it to the consumer given to it at initialization
time.

Updates are sent to the consumer as complete lines (including newlines).
Infile progress is tracked via a persistent state object, which tracks
the inode and file offset.
"""

import codecs
import logging
import os
import os.path

from zope import interface
from twisted.internet import inotify
from twisted.internet import interfaces
from twisted.python import filepath


class LogSnarf(object):
    """Main logsnarf class.
    
    implements :twisted:`twisted.internet.interfaces.IPushProducer`
    """
    interface.implements(interfaces.IPushProducer)

    def __init__(self, state_obj, consumer, reactor=None):
        """Initialize a LogSnarf object.

        :param state_obj: current state
        :type state_obj: logsnarf.state.State
        :param consumer: a consumer object
        :type consumer:
            implements(:twisted:`twisted.internet.interfaces.IConsumer`)
        """
        if not reactor:
            from twisted.internet import reactor
        self.consumer = consumer
        self.reactor = reactor
        self._inotifier = inotify.INotify(reactor=self.reactor)
        self._callback = None
        self._state = state_obj
        self._patterns = {}
        self._paused_in_doRead = []
        self.paused = True
        self.log = logging.getLogger(self.__class__.__name__)
        self.consumer.registerProducer(self, True)
        self.setCallback(self.consumer.write)

    def watch(self, path, pattern=None, recursive=True):
        """Add a watch to a given directory.

        :param path: directory to watch for changes in
        :param pattern: regular expression that files much match
        :param recursive: If true, also watch subdirectories.

        :type path: string or :twisted:`twisted.python.filepath.FilePath`
        :type pattern: re.RegexObject or None
        :type recursive: bool
        """
        if not isinstance(path, filepath.FilePath):
            path = filepath.FilePath(path)
        self._patterns[path.path] = pattern
        # noinspection PyUnresolvedReferences
        self.reactor.callWhenRunning(self._do_backlog, path, pattern,
                                     recursive)
        self._inotifier.watch(path, recursive=recursive, autoAdd=True,
                              callbacks=[self._snarfcb],
                              mask=inotify.IN_MODIFY | inotify.IN_DELETE)

    def _do_backlog(self, path, pattern, recursive):
        """Process the backlog.

        Files we know about are processed from last offset, new files
        are processed and added to the state file.
        """
        self.log.info("Processing backlog in %s pattern: %s recursive: %s",
                      path.path, pattern.pattern, recursive)
        if recursive:
            filenames = []
            for dirpath, _, filename in os.walk(path.path):
                filenames.extend([os.path.join(dirpath, f) for f in filename])
        else:
            filenames = [
                os.path.join(path.path, f) for f in os.listdir(path.path)
            ]
        if pattern:
            filenames = filter(pattern.match, filenames)

        self.log.info("Files to process as backlog %s", filenames)
        filenames = map(filepath.FilePath, filenames)

        map(self.doRead, filenames)

    def start(self):
        """Start watching."""
        self._inotifier.startReading()
        self.paused = False

    def setCallback(self, callback):
        """Add a callback function.

        The callback should have a signature of f(line), accepting one line
        (including newline) of text.
        """
        if not callable(callback):
            self.log.error('Attempt to add a non callable callback %r',
                           callback)
            raise TypeError('%r is not callable.', callback)
        if hasattr(callback, 'im_class'):
            name = '%s.%s' % (callback.im_class, callback.__name__)
        else:
            name = callback.__name__
        self.log.debug('Callback set to %s', name)
        self._callback = callback

    def pauseProducing(self):
        """:twisted:`twisted.internet.interfaces.IPushProducer` method

        Pause producing.
        """
        self.paused = True
        self._inotifier.pauseProducing()
        self.log.debug('Paused producing')

    def resumeProducing(self):
        """:twisted:`twisted.internet.interfaces.IPushProducer` method

        Resume producing.
        """
        self.paused = False
        self.log.debug('Resuming production')
        for path in self._paused_in_doRead[:]:
            # We can be paused during one of these calls.
            if self.paused:
                return
            self.log.debug('Resuming read of %s', path.path)
            self._paused_in_doRead.remove(path)
            self.doRead(path)
        self.log.debug('Resuming inotify')
        self._inotifier.resumeProducing()

    def cleanState(self):
        """Remove invalid entries from the state file."""
        for path in self._state:
            if not os.path.exists(path):
                self._state.pop(path, None)

    def checkPattern(self, path):
        """Check a path against our pattern.

        :param twisted.python.filepath.FilePath: path to check
        :returns bool: true if the path matches.
        """
        # Start with most specific (longest) path
        for pth in sorted(self._patterns, reverse=True,
                          key=lambda x: len(x.path)):
            if path.path.startswith(pth.path):
                if self._patterns[pth] is None or \
                        self._patterns[pth].search(path.path):
                    return True
        return False

    def doRead(self, path):
        """read from a file.

        :param path: the file to read
        :type path: :twisted:`twisted.python.filepath.FilePath`
        """
        path.restat()
        offset, inode = self._state.get(path.path, [0, path.getInodeNumber()])
        new_inode = path.getInodeNumber()

        if inode != new_inode:
            self.log.warning('%s is a new file, inodes differ. Starting '
                             'from offset 0', path.path)
            offset = 0
            inode = new_inode
        elif path.getsize() < offset:
            self.log.warning('The file at %s is of size %d, shorter than our '
                             'previous offset, which was %d. Starting from '
                             'offset 0', path.path, path.getsize(), offset)
            offset = 0
        self.log.debug('do_read: %s offset: %d', path.path, offset)
        try:
            with path.open() as raw_fp:
                f = codecs.getreader('utf-8')(raw_fp, errors='ignore')
                if offset != 0:
                    f.seek(offset - 1)
                    c = f.read(1)
                    if c != '\n':
                        offset = self._seekNewLine(f, offset)
                        f.seek(offset)
                line = True
                while line:
                    line = f.readline()
                    if line.endswith('\n'):
                        # the reader looks ahead, we need to offset this when
                        # storing, well, offsets
                        offset = f.tell()
                        if f.charbuffer is not None:
                            offset -= len(f.charbuffer)
                        self._callback(line)
                        if self.paused:
                            self.log.debug('Paused by consumer')
                            self._paused_in_doRead.append(path)
                            self._state[path.path] = [offset, inode]
                            return

                self._state[path.path] = [offset, inode]
        except IOError:
            self.log.exception('error while processing %s', path)

    def _seekNewLine(self, fp, offset):
        """Seek backwards to the first newline in fp from offset."""
        fp.seek(offset - 4096)
        buf = fp.read(4096)
        new_offset = offset - 4096 + buf.rfind('\n') + 1
        self.log.debug('Rewinding %r to %d', fp, new_offset)
        fp.seek(new_offset)
        return new_offset

    def _snarfcb(self, _, path, mask):
        """The callback given to :twisted:`twisted.internet.inotify.INotify`"""
        if mask & inotify.IN_DELETE:
            self._state.pop(path.path, None)
            return
        if not mask & inotify.IN_MODIFY:
            return
        if not self.checkPattern(path):
            return
        self.doRead(path)
