import cStringIO
import datetime
import logging

import pytz
from twisted.trial import unittest

from .. import schema
from .. import errors
from . import schema_test_utils


BASIC_SCHEMA = """
[
    {
        "mode": "REQUIRED",
        "name": "fielda",
        "type": "STRING",
        "description": "field a"
    },
    {
        "mode": "REQUIRED",
        "name": "fieldb",
        "type": "INTEGER",
        "description": "field b"
    }
]"""

BASIC_INPUT = """{ "fielda": "hello", "fieldb": 5 }"""


class SchemaTestCaseAutoTests(unittest.TestCase):
    __metaclass__ = schema_test_utils.AutoSchemaTest


class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.sch = schema.Schema(cStringIO.StringIO(BASIC_SCHEMA))
        nullHandler = logging.NullHandler()
        self.log = logging.getLogger()
        self.log.handlers = [nullHandler]

    def test_SchemaDescriptionTooLong(self):
        schema_json = """
[
    {
        "mode": "REQUIRED",
        "name": "imtoolong",
        "type": "STRING",
        "description": "%s"
    }
]"""
        # make sure it loads with a short description.
        schema.Schema(cStringIO.StringIO(schema_json % "foo"))
        self.assertRaises(
            errors.ValidationError,
            schema.Schema,
            cStringIO.StringIO(schema_json % ('x' * 16385, )),
        )

    def test_setFieldValidator(self):
        result = self.sch.loads(BASIC_INPUT)
        self.assertEquals(result['fieldb'], 5)

        self.sch.setFieldValidator('fieldb', lambda x, y: y * 5)
        result = self.sch.loads(BASIC_INPUT)
        self.assertEquals(result['fieldb'], 25)

    def test_setInvalidFieldValidator(self):
        self.assertRaises(errors.ValidatorError,
                          self.sch.setFieldValidator,
                          'fieldb',
                          'foo')

    def test_setValidatorInvalidField(self):
        self.assertRaises(errors.ValidatorError,
                          self.sch.setFieldValidator,
                          'unfield',
                          lambda x, y: y)

    def test_datetime_tounix(self):
        in_date = datetime.datetime.utcnow()
        ts = schema.datetime_to_unix(in_date)
        out_date = datetime.datetime.fromtimestamp(ts)
        self.assertEqual(in_date, out_date)

    def test_datetime_tounix_with_tz(self):
        tz = pytz.timezone('Australia/Sydney')
        in_date = datetime.datetime.now(tz=tz)
        ts = schema.datetime_to_unix(in_date)
        out_date = datetime.datetime.fromtimestamp(ts, tz=pytz.UTC)
        self.assertEqual(in_date, out_date)

