import ConfigParser
import os

from twisted.trial import unittest
import mock
from mock import sentinel

from logsnarf import config


CONFIG = {
    'test1': {
        'opt1': 'val1',
        'opt2': 'val2',
    },
    'test2': {
        'opt1': 'val3',
        'testint': '35',
        'testbool': 'true',
        'testbool2': 'false',
        'testfloat': '355.221',
        'testfloat2': '35.0',
    }
}


class ConfigSectionTestCase(unittest.TestCase):
    def setUp(self):
        self.cp = cp = ConfigParser.SafeConfigParser()
        for section in CONFIG:
            cp.add_section(section)
            for opt in CONFIG[section]:
                cp.set(section, opt, CONFIG[section][opt])

    def test_configSectionBasic(self):
        test_section = 'test1'
        section = config.ConfigSection(test_section, self.cp)
        self.assertEquals(section['opt1'], CONFIG[test_section]['opt1'])
        self.assertEquals(section['opt2'], CONFIG[test_section]['opt2'])
        self.assertEquals(len(section), 2)

    def test_configSectionInt(self):
        test_section = 'test2'
        section = config.ConfigSection(test_section, self.cp)
        self.assertTrue(isinstance(section['testint'], int))

    def test_configSectionBool(self):
        test_section = 'test2'
        section = config.ConfigSection(test_section, self.cp)
        self.assertTrue(isinstance(section['testbool'], bool))
        self.assertTrue(isinstance(section['testbool2'], bool))

    def test_configSectionFloat(self):
        test_section = 'test2'
        section = config.ConfigSection(test_section, self.cp)
        self.assertTrue(isinstance(section['testfloat'], float))
        self.assertTrue(isinstance(section['testfloat2'], float))


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.patchers = []

        p = mock.patch('xdg.BaseDirectory.save_config_path')
        self.save_config_path = p.start()
        self.save_config_path.return_value = '/some/save/path'
        self.patchers.append(p)

        p = mock.patch('xdg.BaseDirectory.save_data_path')
        self.save_data_path = p.start()
        self.save_data_path.return_value = '/some/data/path'
        self.patchers.append(p)

        p = mock.patch('xdg.BaseDirectory.load_config_paths')
        self.load_config_paths = p.start()
        self.load_config_paths.return_value = [
            '/some/save/path',
            '/usr/local/lib/config/path',
            '/usr/lib/config/path',
        ]
        self.patchers.append(p)

        p = mock.patch('ConfigParser.SafeConfigParser')
        o = p.start()
        self.configparser = o.return_value
        self.patchers.append(p)
        self.config = config.Config()

    def tearDown(self):
        super(ConfigTestCase, self).tearDown()
        for p in self.patchers:
            p.stop()
        self.configparser.reset_mock()
        del self.config

    def test_init(self):
        self.assertEquals(self.config.resource_name, 'logsnarf')
        self.assertEquals(self.config.config_file, None)
        self.assertEquals(self.config._cp, self.configparser)

    @mock.patch('logsnarf.config.ConfigSection')
    def test_loadConfigs(self, mock_section):
        # noinspection PyUnusedLocal
        def section_init(sname, cparser):
            return getattr(sentinel, sname)

        mock_section.side_effect = section_init
        self.configparser.sections.return_value = ['test1', 'test2']
        self.config.loadConfigs()
        self.assertEquals(self.config['test1'], sentinel.test1)
        self.assertEquals(len(self.config), 2)
        expected_load_paths = [
            os.path.join(p, 'logsnarf.ini') for p in
            self.load_config_paths.return_value
        ]
        expected_load_paths.reverse()
        # the call argument is an iterator
        call_args = [p for p in self.configparser.read.call_args[0][0]]
        self.assertListEqual(expected_load_paths, call_args)

    def test_loadConfigsConfigFile(self):
        self.config.config_file = 'testme'
        self.config.loadConfigs()
        self.assertEquals(len(self.config), 0)
        self.configparser.read.assert_called_once_with('testme')

    @mock.patch('os.path.exists')
    @mock.patch('logging.basicConfig')
    def test_loadLoggingConfigBasicConfig(self, basicConfig, exists):
        exists.return_value = False
        self.config.loadLoggingConfig()
        basicConfig.assert_called_once_with()

    @mock.patch('os.path.exists')
    @mock.patch('logging.config.fileConfig')
    def test_loadLoggingConfigFileConfig(self, fileConfig, exists):
        def exist_return(path):
            if path.startswith('/some/save/path'):
                return True
            return False

        exists.side_effect = exist_return
        self.config.loadLoggingConfig()
        fileConfig.assert_called_once_with(
            os.path.join('/some/save/path', 'logging.ini'))

    def test_openConfigfile(self):
        m = mock.mock_open(read_data='contents')
        with mock.patch('logsnarf.config.open', m, create=True):
            f = self.config.openConfigFile('test.ini', 'rb')
            self.assertEquals(f.read(), 'contents')
        m.assert_has_calls([
            mock.call(os.path.join('/some/save/path', 'test.ini'), 'rb'),
            mock.call().read()
        ])

    def test_openDataFile(self):
        m = mock.mock_open(read_data='contents')
        with mock.patch('logsnarf.config.open', m, create=True):
            f = self.config.openDataFile('test.dat', 'rb')
            self.assertEquals(f.read(), 'contents')
        m.assert_has_calls([
            mock.call(os.path.join('/some/data/path', 'test.dat'), 'rb'),
            mock.call().read()
        ])

    def test_saveConfigPath(self):
        self.assertEquals(self.config.saveConfigPath(), '/some/save/path')
        self.assertEquals(self.config.saveConfigPath('file'),
                          os.path.join('/some/save/path', 'file'))

    def test_saveDataPath(self):
        self.assertEquals(self.config.saveDataPath(), '/some/data/path')
        self.assertEquals(self.config.saveDataPath('file2'),
                          os.path.join('/some/data/path', 'file2'))

        pass

    def test_loadConfigPaths(self):
        self.assertEquals(self.config.loadConfigPaths(),
                          self.load_config_paths.return_value)
