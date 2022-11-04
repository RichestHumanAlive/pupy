
"""
**NetRef**: a transparent *network reference*. This module contains quite a lot
of *magic*, so beware.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import sys
import inspect
import types

from pupy.network.lib.compat import (
    pickle, is_py3k, maxint, as_native_string
)

from . import consts


_local_netref_attrs = frozenset([
    '____conn__', '____oid__', '____refcount__', '___async_call__',
    '___methods__',

    '__class__', '__cmp__',
    '__del__', '__delattr__',
    '__dir__', '__doc__', '__getattr__', '__getattribute__', '__hash__',
    '__init__', '__metaclass__', '__module__', '__new__', '__reduce__',
    '__reduce_ex__', '__repr__', '__setattr__', '__slots__', '__str__',
    '__weakref__', '__dict__', '__members__'
])
"""the set of attributes that are local to the netref object"""

_builtin_types = [
    type, object, bool, complex, dict, float, int, list,
    slice, str, tuple, set, frozenset, Exception, type(None),
    types.BuiltinFunctionType, types.GeneratorType,
    types.MethodType, types.CodeType, types.FrameType,
    types.TracebackType, types.ModuleType, types.FunctionType,

    type(int.__add__),      # wrapper_descriptor
    type((1).__add__),      # method-wrapper
    type(iter([])),         # listiterator
    type(iter(())),         # tupleiterator
    type(iter(set())),      # setiterator
]

"""a list of types considered built-in (shared between connections)"""

try:
    BaseException
except NameError:
    pass
else:
    _builtin_types.append(BaseException)

if is_py3k:
    _builtin_types.extend([
        bytes, bytearray, type(iter(range(10))), memoryview,
    ])
    xrange = range
else:
    _builtin_types.extend([
        basestring, unicode, long, xrange, type(iter(xrange(10))), file,
        types.InstanceType, type, types.DictProxyType,
    ])

_normalized_builtin_types = dict(
    ((t.__name__, t.__module__), t)
    for t in _builtin_types
)


class byref(object):
    __slots__ = ('object',)

    def __init__(self, obj):
        self.object = obj


def syncreq(proxy, handler, *args):
    """Performs a synchronous request on the given proxy object.
    Not intended to be invoked directly.

    :param proxy: the proxy on which to issue the request
    :param handler: the request handler (one of the ``HANDLE_XXX`` members of
                    ``.protocol.consts``)
    :param args: arguments to the handler

    :raises: any exception raised by the operation will be raised
    :returns: the result of the operation
    """
    conn = object.__getattribute__(proxy, "____conn__")()
    if not conn:
        raise ReferenceError('weakly-referenced object no longer exists')
    oid = object.__getattribute__(proxy, "____oid__")
    return conn.sync_request(handler, oid, *args)


def asyncreq(proxy, handler, *args):
    """Performs an asynchronous request on the given proxy object.
    Not intended to be invoked directly.

    :param proxy: the proxy on which to issue the request
    :param handler: the request handler (one of the ``HANDLE_XXX`` members of
                    ``.protocol.consts``)
    :param args: arguments to the handler

    :returns: an :class:`AsyncResult <.core.async.AsyncResult>` representing
              the operation
    """
    conn = object.__getattribute__(proxy, "____conn__")()
    if not conn:
        raise ReferenceError('weakly-referenced object no longer exists')
    oid = object.__getattribute__(proxy, "____oid__")
    return conn.async_request(handler, oid, *args)


class NetrefMetaclass(type):
    """A *metaclass* used to customize the ``__repr__`` of ``netref`` classes.
    It is quite useless, but it makes debugging and interactive programming
    easier"""

    __slots__ = ()

    def __repr__(self):
        if self.__module__:
            return "<netref class '%s.%s'>" % (self.__module__, self.__name__)
        else:
            return "<netref class '%s'>" % (self.__name__,)


class BaseNetref(object):
    """The base netref class, from which all netref classes derive. Some netref
    classes are "pre-generated" and cached upon importing this module (those
    defined in the :data:`_builtin_types`), and they are shared between all
    connections.

    The rest of the netref classes are created by
    :meth:`.core.protocl.Connection._unbox`, and are private to the connection.

    Do not use this class directly; use :func:`class_factory` instead.

    :param conn: the :class:`.core.protocol.Connection` instance
    :param oid: the unique object ID of the remote object
    """
    # this is okay with py3k -- see below

    __metaclass__ = NetrefMetaclass
    __slots__ = (
        '____conn__', '____oid__', '__weakref__', '____refcount__',
        '___async_call__'
    )

    def __init__(self, conn, oid):
        self.____conn__ = conn
        self.____oid__ = oid
        self.____refcount__ = 1
        self.___async_call__ = None

    def __del__(self):
        # print('DEL', repr((type(self), repr(self))))
        try:
            asyncreq(self, consts.HANDLE_DEL, self.____refcount__)
        except Exception:
            # raised in a destructor, most likely on program termination,
            # when the connection might have already been closed.
            # it's safe to ignore all exceptions here
            pass

    def __getattribute__(self, name):
        methods = object.__getattribute__(self, '___methods__')
        method = methods.get(name)
        if method is not None:
            bound_method = method.__get__(self)
            setattr(
                bound_method, '___async_call__',
                method.___async_call__.__get__(self)
            )

            return bound_method

        if name in _local_netref_attrs:
            if name == '__class__':
                cls = object.__getattribute__(self, '__class__')
                if cls is None:
                    cls = self.__getattr__('__class__')
                return cls
            elif name == '__doc__':
                return self.__getattr__('__doc__')
            elif name == '__members__':  # for Python < 2.6
                return self.__dir__()
            elif name == '___async_call__':
                call = methods.get('__call__')
                if call is None:
                    return None

                return call.___async_call__.__get__(self)
            else:
                return object.__getattribute__(self, name)
        elif name == '__call__':  # IronPython issue #10
            return object.__getattribute__(self, '__call__')
        else:
            # print('GETATTRIBUTE', repr((type(self), repr(name), repr(self))))
            return syncreq(self, consts.HANDLE_GETATTR, name)

    def __getattr__(self, name):
        # print('GETATTR', repr((type(self), name)))
        return syncreq(
            self, consts.HANDLE_GETATTR,
            as_native_string(name)
        )

    def __delattr__(self, name):
        if name in _local_netref_attrs:
            object.__delattr__(
                self, as_native_string(name)
            )
        else:
            # print('DELATTR', repr((type(self), name)))
            asyncreq(
                self, consts.HANDLE_DELATTR,
                as_native_string(name)
            )

    def __setattr__(self, name, value):
        if name in _local_netref_attrs:
            object.__setattr__(
                self, as_native_string(name), value
            )
        else:
            # print('SETATTR', repr((type(self), name)))
            asyncreq(
                self, consts.HANDLE_SETATTR,
                as_native_string(name), value
            )

    def __dir__(self):
        # print('DIR', repr((type(self))))
        return list(
            as_native_string(key) for key in syncreq(
                self, consts.HANDLE_DIR
            )
        )

    # support for metaclasses
    def __hash__(self):
        # print('HASH', repr((type(self))))
        return syncreq(self, consts.HANDLE_HASH)

    def __iter__(self):
        # print('ITER', repr((type(self))))
        return syncreq(
            self, consts.HANDLE_CALLATTR, '__iter__'
        )

    def __cmp__(self, other):
        # print('CMP', repr((type(self))))
        return syncreq(self, consts.HANDLE_CMP, other)

    def __repr__(self):
        # print('REPR', repr((type(self))))
        # __repr__ MUST return string
        return as_native_string(syncreq(self, consts.HANDLE_REPR))

    def __str__(self):
        # print('STR', repr((type(self))))
        # __str__ MUST return string
        return as_native_string(syncreq(self, consts.HANDLE_STR))

    # support for pickling netrefs
    def __reduce_ex__(self, proto):
        return pickle.loads, (syncreq(self, consts.HANDLE_PICKLE, proto),)


if not isinstance(BaseNetref, NetrefMetaclass):
    # python 2 and 3 compatibe metaclass...
    ns = dict(BaseNetref.__dict__)
    for slot in BaseNetref.__slots__:
        ns.pop(slot)
    BaseNetref = NetrefMetaclass(BaseNetref.__name__, BaseNetref.__bases__, ns)


def _make_method(name, doc):
    """creates a method with the given name and docstring that invokes
    :func:`syncreq` on its `self` argument"""

    slicers = {
        '__getslice__': '__getitem__',
        '__delslice__': '__delitem__',
        '__setslice__': '__setitem__'
    }

    name = as_native_string(name)  # IronPython issue #10
    if name == '__call__':
        def __call__(_self, *args, **kwargs):
            kwargs = tuple(kwargs.items())

            return syncreq(_self, consts.HANDLE_CALL, args, kwargs)

        def ___async_call__(_self, *args, **kwargs):
            kwargs = tuple(kwargs.items())

            return asyncreq(_self, consts.HANDLE_CALL, args, kwargs)

        __call__.__doc__ = doc
        ___async_call__.__doc__ = doc + ' (async)'

        setattr(__call__, '___async_call__', ___async_call__)
        setattr(___async_call__, '___async_call__', ___async_call__)
        return __call__

    elif name in slicers:
        def method(self, start, stop, *args):
            if stop == maxint:
                stop = None

            return syncreq(
                self, consts.HANDLE_OLDSLICING, slicers[name],
                name, start, stop, args
            )

        def async_method(self, start, stop, *args):
            if stop == maxint:
                stop = None

            return asyncreq(
                self, consts.HANDLE_OLDSLICING, slicers[name],
                name, start, stop, args
            )

        method.__name__ = name
        method.__doc__ = doc

        async_method.__name__ = name
        async_method.__doc__ = doc + ' (async)'

        setattr(method, '___async_call__', async_method)
        setattr(async_method, '___async_call__', async_method)
        return method

    else:
        def method(_self, *args, **kwargs):
            kwargs = tuple(kwargs.items())
            return syncreq(
                _self, consts.HANDLE_CALLATTR, name, args, kwargs
            )

        def async_method(_self, *args, **kwargs):
            # print("ASYNC METHOD CALL ARGS", _self, args, kwargs)
            kwargs = tuple(kwargs.items())
            return asyncreq(
                _self, consts.HANDLE_CALLATTR, name, args, kwargs
            )

        method.__name__ = name
        method.__doc__ = doc

        async_method.__name__ = name
        async_method.__doc__ = doc + ' (async)'

        setattr(method, '___async_call__', async_method)
        setattr(async_method, '___async_call__', async_method)
        return method


def inspect_methods(obj):
    """introspects the given (local) object, returning a list of all of its
    methods (going up the MRO).

    :param obj: any local (not proxy) python object

    :returns: a list of ``(method name, docstring)`` tuples of all the methods
              of the given object
    """
    methods = {}
    attrs = {}
    if isinstance(obj, type):
        # don't forget the darn metaclass
        mros = list(reversed(type(obj).__mro__)) + list(reversed(obj.__mro__))
    else:
        mros = reversed(type(obj).__mro__)
    for basecls in mros:
        attrs.update(basecls.__dict__)
    for name, attr in attrs.items():
        if name not in _local_netref_attrs and hasattr(attr, "__call__"):
            methods[name] = inspect.getdoc(attr)
    return methods.items()


def class_factory(clsname, modname, methods):
    """Creates a netref class proxying the given class

    :param clsname: the class's name
    :param modname: the class's module name
    :param methods: a list of ``(method name, docstring)`` tuples, of the methods
                    that the class defines

    :returns: a netref class
    """
    clsname = as_native_string(clsname)
    modname = as_native_string(modname)

    ns = {
        '__slots__': (),
        '___methods__': {}
    }

    for name, doc in methods:
        name = as_native_string(name)
        doc = as_native_string(doc) if doc else ''

        if name == 'next':
            ns['__next__'] = _make_method(name, doc)

        if name not in _local_netref_attrs:
            wrapper = _make_method(name, doc)
            ns[name] = wrapper
            ns['___methods__'][name] = wrapper

    ns['__module__'] = modname

    if modname in sys.modules and hasattr(sys.modules[modname], clsname):
        ns['__class__'] = getattr(sys.modules[modname], clsname)

    elif (clsname, modname) in _normalized_builtin_types:
        ns['__class__'] = _normalized_builtin_types[clsname, modname]

    else:
        # to be resolved by the instance
        ns['__class__'] = None

    return type(clsname, (BaseNetref,), ns)


builtin_classes_cache = {}
"""The cache of built-in netref classes (each of the types listed in
:data:`_builtin_types`). These are shared between all  connections"""


# init the builtin_classes_cache
for cls in _builtin_types:
    builtin_classes_cache[cls.__name__, cls.__module__] = class_factory(
        cls.__name__, cls.__module__, inspect_methods(cls))
