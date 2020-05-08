"""
Backfills for contextlib goodies added in Python 3.7+

PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
--------------------------------------------

1. This LICENSE AGREEMENT is between the Python Software Foundation
("PSF"), and the Individual or Organization ("Licensee") accessing and
otherwise using this software ("Python") in source or binary form and
its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
analyze, test, perform and/or display publicly, prepare derivative works,
distribute, and otherwise use Python alone or in any derivative version,
provided, however, that PSF's License Agreement and PSF's notice of copyright,
i.e., "Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009,
2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020 Python
Software Foundation; All Rights Reserved" are retained in Python alone or in
any derivative version prepared by Licensee.

3. In the event Licensee prepares a derivative work that is based on
or incorporates Python or any part thereof, and wants to make
the derivative work available to others as provided herein, then
Licensee hereby agrees to include in any such work a brief summary of
the changes made to Python.

4. PSF is making Python available to Licensee on an "AS IS"
basis.  PSF MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, PSF MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON,
OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

6. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

7. Nothing in this License Agreement shall be deemed to create any
relationship of agency, partnership, or joint venture between PSF and
Licensee.  This License Agreement does not grant permission to use PSF
trademarks or trade name in a trademark sense to endorse or promote
products or services of Licensee, or any third party.

8. By copying, installing or otherwise using Python, Licensee
agrees to be bound by the terms and conditions of this License
Agreement.
"""
import abc
import contextlib
from collections import abc as collections_abc
from functools import wraps

if hasattr(contextlib, 'asynccontextmanager'):
    asynccontextmanager = contextlib.asynccontextmanager
else:
    def asynccontextmanager(func):
        print('bad one')

        @wraps(func)
        def helper(*args, **kwds):
            return _AsyncGeneratorContextManager(func, args, kwds)

        return helper


    class _GeneratorContextManagerBase:
        """Shared functionality for @contextmanager and @asynccontextmanager."""

        def __init__(self, func, args, kwds):
            self.gen = func(*args, **kwds)
            self.func, self.args, self.kwds = func, args, kwds

            doc = getattr(func, "__doc__", None)
            if doc is None:
                doc = type(self).__doc__
            self.__doc__ = doc


    class AbstractAsyncContextManager(abc.ABC):
        """An abstract base class for asynchronous context managers."""

        async def __aenter__(self):
            """Return `self` upon entering the runtime context."""
            return self

        @abc.abstractmethod
        async def __aexit__(self, exc_type, exc_value, traceback):
            """Raise any exception triggered within the runtime context."""
            return None

        @classmethod
        def __subclasshook__(cls, C):
            if cls is AbstractAsyncContextManager:
                return collections_abc._check_methods(C, "__aenter__",
                                                      "__aexit__")
            return NotImplemented


    class _AsyncGeneratorContextManager(_GeneratorContextManagerBase,
                                        AbstractAsyncContextManager):
        """Helper for @asynccontextmanager."""

        async def __aenter__(self):
            try:
                return await self.gen.__anext__()
            except StopAsyncIteration:
                raise RuntimeError("generator didn't yield") from None

        async def __aexit__(self, typ, value, traceback):
            if typ is None:
                try:
                    await self.gen.__anext__()
                except StopAsyncIteration:
                    return
                else:
                    raise RuntimeError("generator didn't stop")
            else:
                if value is None:
                    value = typ()
                # See _GeneratorContextManager.__exit__ for comments on subtleties
                # in this implementation
                try:
                    await self.gen.athrow(typ, value, traceback)
                    raise RuntimeError("generator didn't stop after throw()")
                except StopAsyncIteration as exc:
                    return exc is not value
                except RuntimeError as exc:
                    if exc is value:
                        return False
                    # Avoid suppressing if a StopIteration exception
                    # was passed to throw() and later wrapped into a RuntimeError
                    # (see PEP 479 for sync generators; async generators also
                    # have this behavior). But do this only if the exception wrapped
                    # by the RuntimeError is actully Stop(Async)Iteration (see
                    # issue29692).
                    if isinstance(value, (StopIteration, StopAsyncIteration)):
                        if exc.__cause__ is value:
                            return False
                    raise
                except BaseException as exc:
                    if exc is not value:
                        raise
