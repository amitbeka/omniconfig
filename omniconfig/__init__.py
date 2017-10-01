# encoding: utf-8
"""Configuration from python code, environment and command line"""
from __future__ import unicode_literals, division

import collections
import functools
import os
import argparse


class Parameter(collections.namedtuple(
        'Parameter', ['value', 'type_', 'docstring', 'envvar'])):
    """Immutable container for configuration paramter options.

    Attributes:
        value: the default value for this parameter
        type_: the type conversion from a string to the value
        docstring: documentation of what this parameter means
        envvar: name of environment variable which contains non-default value

    """
    def __new__(cls, value, type_=None, docstring='', envvar=None):
        return super(Parameter, cls).__new__(cls, value, type_, docstring,
                                             envvar)


class _ArgparseAction(argparse.Action): # pylint:disable=too-few-public-methods
    """Custom argparse.Action class which sets the value in a Config object when called"""

    def __call__(self, parser, namespace, values, option_string=None):
        """In addition to setting the value to the namespace, also set in Config object"""
        setattr(parser.config_instance, '_' + self.dest, values)
        return super(_ArgparseAction, self).__call__(parser, namespace, values, option_string)


class ConfigMeta(type):
    """Metaclass for configuration objects.

    Used to convert class attributes to properties and override class creation
    so the Config object will be a singelton.

    """

    def __new__(mcs, clsname, bases, attrs):

        def get_static(self, name):
            """Return self.name"""
            return getattr(self, name)

        def get_callable(self, name, func):
            """Return self.name if exists, or calls `func` and sets it before returning"""
            return self.__dict__.setdefault(name, func())

        config_params = {}
        for base in bases:
            config_params.update(getattr(base, 'config_params', {}))

        new_attrs = {'config_params': config_params}
        for name, value in attrs.iteritems():
            if name in config_params: # we just override the value
                config_params[name] = config_params[name]._replace(value=value)
                new_attrs['_' + name] = value
                continue
            if not isinstance(value, Parameter):
                new_attrs[name] = value
                continue
            param = value
            if callable(param.value):
                getter = functools.partial(get_callable, name='_' + name, func=param.value)
            else:
                new_attrs['_' + name] = param.value
                getter = functools.partial(get_static, name='_' + name)
            new_attrs[name] = property(getter, doc=param.docstring)
            new_attrs['config_params'][name] = param
        return super(ConfigMeta, mcs).__new__(mcs, clsname, bases, new_attrs)

    def __init__(cls, name, bases, dct):
        super(ConfigMeta, cls).__init__(name, bases, dct)
        cls.__instance = None

    def __call__(cls, *args, **kw):
        if cls.__instance is None:
            cls.__instance = super(ConfigMeta, cls).__call__(*args, **kw)
        return cls.__instance


class Config(object):
    """Configuration class which supports seamless integration between different sources."""

    __metaclass__ = ConfigMeta

    def __init__(self):
        """Override default values with environment variables"""
        for name, param in self.config_params.iteritems(): # pylint:disable=no-member
            if param.envvar and os.environ.get(param.envvar):
                setattr(self, '_' + name, param.type_(os.environ.get(param.envvar)))

    def get_argparse(self, param_names, **kwargs):
        """Return an ArgumentParser instance with options for all `param_names`.

        `param_names` is a list of strings, one for each parameter which we want to expose.
        For example, if param_names == ['port', 'ip'], then the returned ArgumentParser
        will have support for '--port' and '--ip', and set their `type` argument
        to their saved types so they will be converted.
        kwargs are passed as is to the ArgumentParser __init__ method.

        """
        parser = argparse.ArgumentParser(**kwargs)
        parser.config_instance = self
        for name in param_names:
            param = self.config_params[name] # pylint: disable=no-member
            parser.add_argument('--' + name, help=param.docstring, default=param.value,
                                type=param.type_, action=_ArgparseAction)
        return parser

    def get_dict(self, strict=False):
        """Return a dictionary of all parameter names and values.

        If `strict`, then only JSON-serializable parameters are returned.

        """
        out = {name: getattr(self, name) for name in self.config_params} # pylint: disable=no-member
        if strict:
            out = {key: value for key, value in out.iteritems()
                   if isinstance(value, (int, bool, float, str, unicode, list, dict))}
        return out

    def set_dict(self, data):
        """Set new values from `data`, overriding only what's inside it"""
        for name, value in data.iteritems():
            self.config_params[name]._replace(value=value)
            setattr(self, '_' + name, value)


def str_bool(x):
    """Return boolean value of `x`, support for false-meaning strings (0, 'false' etc.)"""
    try:
        return x.strip().lower() not in {'0', 'false', 'none', 'null', 'nil', ''}
    except AttributeError: # probably not a string
        return bool(x)
