from twisted.trial import unittest
import mock

from .. import state


class StateTestCase(unittest.TestCase):
    def setUp(self):
        m = mock.mock_open(read_data='{ "foo": "bar", "bar": "zab" }')
        with mock.patch('logsnarf.state.open', m, create=True):
            self.state = state.State('somefakefile.json')

    def test_stateLoad(self):
        self.assertEquals(self.state, {'foo': 'bar', 'bar': 'zab'})

    @mock.patch('json.dump')
    def test_stateSaveOnSet(self, mock_dump):
        m = mock.mock_open()
        with mock.patch('logsnarf.state.open', m, create=True):
            self.state['test'] = 'me'
        mock_dump.assert_called_once_with(self.state, m.return_value,
                                          sort_keys=True)

    @mock.patch('json.dump')
    def test_stateSaveOnRemove(self, mock_dump):
        m = mock.mock_open()
        with mock.patch('logsnarf.state.open', m, create=True):
            self.state.pop('foo')
        mock_dump.assert_called_once_with(self.state, m.return_value,
                                          sort_keys=True)

    def test_invalidStatefile(self):
        m = mock.mock_open(read_data='{ "foo": "bar", "bar": "zab", }')
        with mock.patch('logsnarf.state.open', m, create=True):
            st = state.State('somefakefile.json')
        self.assertIsNotNone(st)
        self.assertDictEqual(st._values, {})

    @mock.patch('os.access')
    def test_stateFileDoesNotExistCanWritePath(self, access):
        m = mock.mock_open()
        access.return_value = True
        m.side_effect = IOError()
        with mock.patch('logsnarf.state.open', m, create=True):
            st = state.State('somefakefile.json')
        self.assertIsNotNone(st)
        self.assertDictEqual(st._values, {})

    @mock.patch('os.access')
    def test_stateFileDoesNotExistCantWritePath(self, access):
        m = mock.mock_open()
        access.return_value = False
        m.side_effect = IOError()
        with mock.patch('logsnarf.state.open', m, create=True):
            self.assertRaises(IOError,
                              state.State,
                              'somefakefile.json')

    @mock.patch('os.path.exists')
    def test_stateFileExistCantRead(self, pathexists):
        m = mock.mock_open()
        pathexists.return_value = True
        m.side_effect = IOError()
        with mock.patch('logsnarf.state.open', m, create=True):
            self.assertRaises(IOError,
                              state.State,
                              'somefakefile.json')