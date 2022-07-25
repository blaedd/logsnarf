import re

import mock
from twisted.internet import inotify
from twisted.internet import interfaces
from twisted.internet import reactor
from twisted.python import filepath
from twisted.trial import unittest
from zope import interface

from logsnarf import snarf


class MockConsumer(object):
    """Mock consumer for testing logsnarf."""
    interface.implements(interfaces.IConsumer)

    def __init__(self):
        self.data = []
        self.producer = None
        self.streaming = None

    def registerProducer(self, producer, streaming):
        self.producer = producer
        self.streaming = streaming

    def write(self, data):
        self.data.append(data)


class LogsnarfTestCase(unittest.TestCase):
    # noinspection PyTypeChecker
    def setUp(self):
        self.consumer = MockConsumer()
        self.reactor = mock.MagicMock(spec=reactor)
        self.inotifier = mock.MagicMock(spec=inotify.INotify)
        self.snarf = snarf.LogSnarf(state_obj={}, consumer=self.consumer,
                                    reactor=self.reactor)
        self.snarf._inotifier = self.inotifier

    def test_LogsnarfInitConsumerSet(self):
        self.assertEqual(self.snarf.consumer, self.consumer)
        self.assertEqual(self.consumer.producer, self.snarf)
        self.assertTrue(self.consumer.streaming)

    def test_LogsnarfInitCallbackSet(self):
        self.assertEqual(self.snarf._callback, self.consumer.write)

    def test_LogsnarfInitWeStartPaused(self):
        self.assertTrue(self.snarf.paused)

    def test_WatchNoPatterns(self):
        watchPath = filepath.FilePath('/foo/bar')
        self.assertDictEqual(self.snarf._patterns, {})
        self.snarf.watch(watchPath, pattern=None, recursive=True)
        self.assertEqual(self.snarf._patterns[watchPath.path], None)
        self.inotifier.watch.assert_called_once_with(watchPath,
                                                     recursive=True,
                                                     autoAdd=True,
                                                     callbacks=[
                                                         self.snarf._snarfcb],
                                                     mask=inotify.IN_MODIFY | inotify.IN_DELETE
                                                     )
        self.reactor.callWhenRunning.assert_called_once_with(
            self.snarf._do_backlog,
            watchPath,
            None,
            True
        )

    def test_watchPatterns(self):
        watchPath = filepath.FilePath('/foo/bar')
        pattern = re.compile(r'.*\.log')
        self.snarf.watch(watchPath, pattern=pattern, recursive=True)
        self.assertEqual(self.snarf._patterns[watchPath.path], pattern)

    def test_start(self):
        self.snarf.start()
        self.assertFalse(self.snarf.paused)
        self.inotifier.startReading.assert_called_once_with()

    def test_setCallback(self):
        def callback():
            pass

        self.snarf.setCallback(callback)
        self.assertEquals(self.snarf._callback, callback)

    def test_setCallbackNotCallable(self):
        self.assertRaises(TypeError, self.snarf.setCallback, 1)

    def test_pauseProducing(self):
        self.snarf.start()
        self.assertFalse(self.snarf.paused)
        self.snarf.pauseProducing()
        self.assertTrue(self.snarf.paused)
        self.inotifier.pauseProducing.assert_called_once_with()

    def test_resumeProducing(self):
        self.assertTrue(self.snarf.paused)
        self.snarf.resumeProducing()
        self.assertFalse(self.snarf.paused)

    def test_resumeProducingWhenPausedInRead(self):
        self.snarf.start()
        self.snarf.doRead = mock.Mock()
        paths = [filepath.FilePath('path1'), filepath.FilePath('path2')]
        self.snarf._paused_in_doRead = paths[:]
        self.snarf.resumeProducing()
        # noinspection PyUnresolvedReferences
        self.assertListEqual(self.snarf.doRead.call_args_list,
                             map(mock.call, paths))

    def test_checkPattern(self):
        patterns = {
            '/var/log': re.compile(r'.*\.log'),
            '/var2/log/': None,
        }
        self.snarf._patterns = patterns
        self.assertTrue(
            self.snarf.checkPattern(filepath.FilePath('/var/log/mail.log')))
        self.assertFalse(
            self.snarf.checkPattern(filepath.FilePath('/var/log/messages')))
        self.assertTrue(
            self.snarf.checkPattern(filepath.FilePath('/var2/log/messages')))
