#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- test-case-name: logsnarf.test.test_schema -*-
# pylint: disable=invalid-name

import datetime
import hashlib
import logging
import re

import arrow
import pytz
import simplejson as json
from dateutil import parser

from . import errors

REQUIRED_FIELD_KEYS = ['name', 'type']
OTHER_FIELD_KEYS = ['mode', 'description', 'fields']
VALID_TYPES = {
    'STRING': 1,
    'INTEGER': 2,
    'FLOAT': 3,
    'BOOLEAN': 4,
    'TIMESTAMP': 5,
    'RECORD': 6,
}
TYPE_N_TO_S = dict([(b, a) for (a, b) in VALID_TYPES.items()])

VALID_MODES = {
    'NULLABLE': 1,
    'REPEATED': 2,
    'REQUIRED': 3,
}


# TODO: This should probably be wrapped in a consumer/producer class.
class Schema(object):
    """The Schema class represents a BigQuery JSON schema.

    Objects of this class are able to

     * load and verify schema files which should contain a JSON
       representation of a list of fields as defined by
       https://cloud.google.com/bigquery/docs/reference/v2/tables#schema.fields
     * parse JSON strings, cooercing where able and appropriate fields to
       appropriate types as defined by the schema.
     * validate python objects against the BigQuery schema.

    """

    ignore_fields = ['table', '_sha1']
    """Fields in this list are permitted, even if they aren't part of the
    schema. In Logsnarf we use this for the tables field, which tells us
    which table this log line belongs in, and we remove it from the entry
    before upload."""

    def __init__(self, schema_file, default_tz=pytz.UTC):
        """
        :param file schema_file:
            File-like object containing the BigQuery JSON schema.
        :param datetime.tzinfo default_tz:
            Timezone to use on date strings that don't contain TZ information.
        :raises ValueError:
            if the schema file doesn't contain valid JSON
        """
        self.default_tz = default_tz
        self.log = logging.getLogger(self.__class__.__name__)
        self.schema = json.load(schema_file)
        self._load_hook = None
        # this is a flattened dictionary of the schema fields, for convenience.
        self.field_dict = None
        # maintain a set of these fields per level. while a record field may
        # not be required, it may *have* required fields. We need to track this.
        self.required_fields = {}
        self.repeated_fields = {}

        self.type_map = {
            'STRING': lambda x, y: y,
            'INTEGER': lambda x, y: int(y),
            'FLOAT': lambda x, y: float(y),
            'TIMESTAMP': self.toUnixTimestamp,
            'RECORD': lambda x, y: y,
        }
        self._postproc = []
        self.validateSchema()

    def setObjectLoadHook(self, fn):
        """Set the object load hook used by json.loads.

        :param callable fn: A callable that takes a non-literal, decoded json
            object, and returns an updated version of that object.

        """
        if callable(fn):
            self._load_hook = fn

    def registerPostprocessor(self, fn):
        """Register a post processor.

        Registers a function to be called on the result of every JSON
        object decoded by the Schema object.

        :param callable fn: A callable that takes on argument, the decoded JSON
                            object, and returns the new version of that object.

        """
        if callable(fn):
            self._postproc.append(fn)

    def clearPostprocessors(self):
        """Removes all post processors."""
        self._postproc = []

    def setFieldValidator(self, field_name, fn):
        """Override the validator for a particular field in the schema.

        :param str field_name: The field name to replace the validator for. If
                               referring to a field of a subrecord, use dotted
                               notation. e.g. recordfield.subrecord.item
        :param callable fn: A callable that recieves the root object,
                            and the current value of the field, and returns the
                            new value. In the case where the value is invalid,
                            it should raise errors.ValidationError
        """
        if field_name in self.field_dict and callable(fn):
            self.field_dict[field_name]['validator'] = fn
        else:
            logging.error('Unable to set custom validator for field %s',
                          field_name)
            errtxt = "Invalid validator %r for %s, " % (fn, field_name)
            if not callable(fn):
                errtxt += "%r is not a callable" % fn
            else:
                errtxt += "%s is not a valid field" % field_name
            raise errors.ValidatorError(errtxt)

    def _postProcess(self, js_object):
        js_object = self.validateJSON(js_object)
        for fn in self._postproc:
            js_object = fn(js_object)
        return js_object

    def loads(self, json_string):
        """Deserialize json_string into a python object.

        This applies all schema checks and post-processors.

        :param string|bytes json_string: utf-8 encoded string containing a JSON
                                    document.
        :return: The JSON document as a python object
        :rtype: dict or list or integer or float or unicode
        :raises logsnarf.errors.ValidationError:
            if the JSON is valid, but does not contain a document that conforms
            to the BigQuery schema.
        :raises ValueError:
            if the string does not contain a valid JSON document.

        """
        if isinstance(json_string, bytes):
            json_string = json_string.decode('utf-8')
        obj = self._postProcess(
            json.loads(json_string, encoding='utf-8',
                       object_hook=self._load_hook))
        obj['_sha1'] = hashlib.sha1(json_string.encode('utf-8')).hexdigest()
        return obj

    def validateSchema(self):
        """Validate that the JSON document we loaded as schema, is valid."""
        try:
            assert isinstance(self.schema, list), \
                'Schema must be a list of fields'
            fields = [('', f.copy()) for f in self.schema]
            field_dict = {}
            while fields:
                name, field = fields.pop()
                self.validateSchemaField(field)
                if 'mode' in field:
                    if field['mode'] == VALID_MODES['REQUIRED']:
                        self.required_fields.setdefault(
                            name, set()).add(field['name'])
                    elif field['mode'] == VALID_MODES['REPEATED']:
                        self.repeated_fields.setdefault(
                            name, set()).add(field['name'])
                if name:
                    name = '.'.join([name, field['name']])
                else:
                    name = field['name']
                if field['type'] == VALID_TYPES['RECORD']:
                    fields.extend([(name, f.copy()) for f in field['fields']])
                field['validator'] = self.type_map[TYPE_N_TO_S[field['type']]]
                field_dict[name] = field
            self.field_dict = field_dict
        except AssertionError as e:
            raise errors.ValidationError(*e.args)

    @staticmethod
    def validateSchemaField(field):
        """Validate a field of a schema.

        For clarity this is implemented with asserts. During normal
        schema validation this is wrapped in a ValidationError in validateSchema

        :param dict field: The field to validate.
        :raises AssertionError: if the field is invalid.
        """
        assert 'name' in field, 'name is required key for fields'
        assert 'type' in field, 'type is a required key for fields'
        assert re.match(r'^\w{1,128}$', field['name']), (
            'name must consist of letters, numbers and underscores. No '
            'longer than 128 characters.')

        assert field['type'] in VALID_TYPES, \
            'type must be one of %s, not %s' % (VALID_TYPES.keys(),
                                                field['type'])
        field['type'] = VALID_TYPES[field['type']]
        if field['type'] == VALID_TYPES['RECORD']:
            assert 'fields' in field, \
                'a field of type RECORD must have fields defined.'
        if 'mode' in field:
            assert field['mode'] in VALID_MODES, \
                'if set, mode must be one of %s' % VALID_MODES.keys()
            field['mode'] = VALID_MODES[field['mode']]
        if 'description' in field:
            assert len(field['description']) < 16384, \
                'description can be no longer than 16K'

    def validateJSON(self, root_obj):
        """Validate that an object matches the BigQuery schema.

        This involves
         * ensuring all fields in the object are known
         * all required fields are present.
         * running the field validators on each field

        :param dict root_obj: the object (dict) to validate against the schema.
        :return: validated object
        :rtype: dict
        :raises logsnarf.errors.ValidationError:
            if the object is not valid against the schema
        """
        # Check required fields
        required_fields = self.required_fields.get('', set())
        fields = set(root_obj.keys()) - set(self.ignore_fields)
        if not required_fields.issubset(fields):
            raise errors.ValidationError('Missing required fields %s' %
                                         (required_fields - fields,))
        # done with sets
        fields = [(root_obj, '', f) for f in fields]
        while fields:
            obj, path, field = fields.pop()
            if path:
                name = '.'.join([path, field])
            else:
                name = field
            # Error on unknown fields.
            if name not in self.field_dict:
                raise errors.ValidationError('Unknown field in input %s' % name)
            field_type = self.field_dict[name]['type']
            field_mode = self.field_dict[name].get('mode', None)

            # Repeated fields *may* be a list
            if field_mode == VALID_MODES['REPEATED']:
                if isinstance(obj[field], list):
                    for i in range(len(obj[field])):
                        try:
                            obj[field][i] = self.field_dict[name]['validator'](
                                root_obj, obj[field][i])
                        except ValueError as e:
                            raise errors.ValidationError(*e.args)
                    continue
            # For records, add the record fields to our stack.
            if field_type == VALID_TYPES['RECORD']:
                for subfield in obj[field]:
                    fields.append((obj[field], name, subfield))
                continue
            else:
                # Call our validators by type. They can also normalize the data.
                try:
                    obj[field] = self.field_dict[name]['validator'](root_obj,
                                                                    obj[field])
                except ValueError as e:
                    raise errors.ValidationError(*e.args)
        return root_obj

    def toUnixTimestamp(self, _parent, value):
        """Validator for TIMESTAMP fields.

        :param dict _parent: Parent of the value.
        :param str or integer or float value: The value to validate.
        :return: validated value
        :rtype: float
        :raises logsnarf.errors.ValidationError:
            if value is not, or can not be converted to, a unix timestamp.

        """

        # It might be a unix timestamp, but as a string.
        if isinstance(value, str):
            try:
                value = float(value)
                return value
            except ValueError:
                pass

            try:
                value = parser.parse(value)
                if not value.tzinfo:
                    return arrow.get(value, self.default_tz).float_timestamp
                return arrow.get(value).float_timestamp
            except ValueError:
                self.log.error('Unable to process timestamp field with '
                               'value %s', value, exc_info=True)

                raise

        if isinstance(value, float) or isinstance(value, int):
            return value

        if hasattr(value, 'tzinfo'):
            if not value.tzinfo:
                return arrow.get(value, tzinfo=self.default_tz).float_timestamp
            return arrow.get(value).float_timestamp

        self.log.error('Passed an unknown type %r value %s to parse as a '
                       'timestamp.', value.__class__, value)
        raise errors.ValidationError('Unknown type in timestamp field.', value)
