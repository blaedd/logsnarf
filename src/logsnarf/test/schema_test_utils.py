#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import importlib

from .. import errors
from .. import schema


SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data',
                          'schema')
TEST_SCHEMAS = [sch for sch in os.listdir(SCHEMA_DIR)
                if os.path.exists(os.path.join(SCHEMA_DIR, sch, 'schema.json'))]


class AutoSchemaTest(type):
    """Metaclass that generates test_ methods based on fixture files.

    The base directory for these files is given by SCHEMA_DIR, in that
    directory, a directory for each schema to test should be created.

    In that schema directory, the schema file should be named schema.json.
    Two optional subdirectories are looked at, called "pass" and "fail".

    Files ended in .json in these directories are used to construct tests. As
    implied, files in the pass directory should success, those in the fail
    directory should cause a ValidationError to be raised. The names of the
    files (which again must end in json) are used to construct the test
    names, so they should be descriptive.

    In the pass directory, optional python files, names as per the input
    files may be present, if they exist and contain a "result" object,
    this is compared to the result of loading the input file through the
    schema, and is expected to be the same.
    """

    def __new__(mcs, name, bases, attrs):
        def test_loadSchema(sch_name):
            def _test_loadSchema(self):
                sch_file = open(os.path.join(
                    SCHEMA_DIR, sch_name, 'schema.json'))
                schema.Schema(sch_file)

            _test_loadSchema.__name__ = 'test_load_schema_%s' % sch_name
            return _test_loadSchema

        def test_input(sch_name, infile, fail):
            def _test_input(self):
                sch_file = open(os.path.join(
                    SCHEMA_DIR, sch_name, 'schema.json'))

                s = schema.Schema(sch_file)
                input_string = open(infile).read()
                if fail:
                    self.assertRaises(errors.ValidationError,
                                      s.loads, input_string)
                else:
                    output = s.loads(input_string)
                    result_name = os.path.basename(infile).rsplit('.', 1)[0]
                    result_module = '.data.schema.%s.pass.%s' % (
                        sch_name, result_name)
                    try:
                        expected = importlib.import_module(result_module,
                                                           'logsnarf.test')
                    except ImportError:
                        expected = None
                    if expected and hasattr(expected, 'result'):
                        self.assertDictEqual(output, expected.result)

            if fail:
                action = 'fail'
            else:
                action = 'pass'
            _test_input.__name__ = 'test_schema_%s_%s_%s' % (
                sch_name, action, os.path.basename(infile).rsplit('.', 1)[0])
            return _test_input

        for test_schema in TEST_SCHEMAS:
            fn = test_loadSchema(test_schema)
            attrs[fn.__name__] = fn
            pass_dir = os.path.join(SCHEMA_DIR, test_schema, 'pass')
            fail_dir = os.path.join(SCHEMA_DIR, test_schema, 'fail')

            for d, fail_arg in [(pass_dir, False), (fail_dir, True)]:
                if os.path.exists(d):
                    for f in os.listdir(d):
                        if f.endswith('.json'):
                            test_file = os.path.join(d, f)
                            fn = test_input(test_schema, test_file,
                                            fail=fail_arg)
                            attrs[fn.__name__] = fn
        return type.__new__(mcs, name, bases, attrs)
