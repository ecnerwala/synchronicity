![CI/CD badge](https://github.com/erikbern/synchronicity/actions/workflows/ci.yml/badge.svg)
[![pypi badge](https://img.shields.io/pypi/v/synchronicity.svg?style=flat)](https://pypi.python.org/pypi/synchronicity)

Python 3 has some amazing support for async programming but it's arguably made it a bit harder to develop libraries. Are you tired of implementing synchronous _and_ asynchronous methods doing basically the same thing? This might be a simple solution for you.

Installing
==========

```
pip install synchronicity
```


Background: why is anything like this needed
============================================

Let's say you have an asynchronous function

```python
async def f(x):
    await asyncio.sleep(1.0)
    return x**2
```

And let's say (for whatever reason) you want to offer a synchronous API to users. For instance maybe you want to make it easy to run your code in a basic script, or a user is building something that's mostly CPU-bound, so they don't want to bother with asyncio.

A "simple" way to create a synchronous equivalent would be to implement a set of synchronous functions where all they do is call [asyncio.run](https://docs.python.org/3/library/asyncio-task.html#asyncio.run) on an asynchronous function. But this isn't a great solution for more complex code:

* It's kind of tedious grunt work to have to do this for every method/function
* [asyncio.run](https://docs.python.org/3/library/asyncio-task.html#asyncio.run) doesn't work with generators
* In many cases, you need to preserve an event loop running between calls.

The last case is particularly challenging. For instance, let's say you are implementing a client to a database that needs to have a persistent connection, and you want to built it in asyncio:

```python
class DBConnection:
    def __init__(self, url):
        self._url = url

    async def connect(self):
        self._connection = await connect_to_database(self._url)

    async def query(self, q):
        return await self._connection.run_query(q)
```

How do you expose a synchronous interface to this code? The problem is that wrapping `connect` and `query` in [asyncio.run](https://docs.python.org/3/library/asyncio-task.html#asyncio.run) won't work since you need to _preserve the event loop across calls_. It's clear we need something slightly more advanced.

How to use this library
=======================

This library offers a simple `Synchronizer` class that creates an event loop on a separate thread, and wraps functions/generators/classes so that synchronous execution happens on that thread. When you call anything, it will detect if you're running in a synchronous or asynchronous context, and behave correspondingly.

* In the synchronous case, it will simply block until the result is available (note that you can make it return a future as well, see later)
* In the asynchronous case, it works just like the usual business of calling asynchronous code

```python
from synchronicity import Synchronizer

synchronizer = Synchronizer()

@synchronizer
async def f(x):
    await asyncio.sleep(1.0)
    return x**2


# Running f in a synchronous context blocks until the result is available
ret = f(42)  # Blocks
print('f(42) =', ret)


async def g():
    # Running f in an asynchronous context works the normal way
    ret = await f(42)
    print('f(42) =', ret)
```

More advanced examples
======================

Generators
----------

The decorator also works on generators:

```python
@synchronizer
async def f(n):
    for i in range(n):
        await asyncio.sleep(1.0)
	yield i


# Note that the following runs in a synchronous context
# Each number will take 1s to print
for ret in f(10):
    print(ret)
```

Synchronizing whole classes
---------------------------

It also operates on classes by wrapping every method on the class:


```python
@synchronizer
class DBConnection:
    def __init__(self, url):
        self._url = url

    async def connect(self):
        self._connection = await connect_to_database(self._url)

    async def query(self, q):
        return await self._connection.run_query(q)


# Now we can call it synchronously, if we want to
db_conn = DBConnection('tcp://localhost:1234')
db_conn.connect()
data = db_conn.query('select * from foo')
```

Returning futures
-----------------

You can also make it return a `Future` object by instantiating the `Synchronizer` class with `return_futures=True`. This can be useful if you want to dispatch many calls from a blocking context, but you want to resolve them roughly in parallel:

```python
from synchronicity import Synchronizer

synchronizer = Synchronizer(return_futures=True)

@synchronizer
async def f(x):
    await asyncio.sleep(1.0)
    return x**2

futures = [f(i) for i in range(10)]  # This returns immediately
rets = [fut.result() for fut in futures]  # This should take ~1s to run, resolving all futures in parallel
print('first ten squares:', rets)
```

De-cluttering tracebacks
------------------------

If you use synchronicity, every call will pass through the `Synchronizer` class, which will lead to ugly tracebacks if there's an exception. If you create the `Synchronizer` with the option `filter_tracebacks=True` (Python 3.7+ only), it will strip out all synchronicity-code from tracebacks.

Using with with other asynchronous code
---------------------------------------

This library can also be useful in purely asynchronous settings, if you have multiple event loops, or if you have some section that is CPU-bound, or some critical code that you want to run on a separate thread for safety. All calls to synchronized functions/generators are thread-safe by design. This makes it a useful alternative to [loop.run_in_executor](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor) for simple things. Note however that each synchronizer only runs one thread.

Metaclasses
-----------

This library is also possible to use with metaclasses. Using a metaclass on a base class, you can make sure any inherited class ends up being "synchronized":

```python
s = Synchronizer()

class ObjectMetaclass(type):
    def __new__(metacls, name, bases, dct):
        new_cls = s.create_class(metacls, name, bases, dct)
        return new_cls


class ObjectBase(metaclass=ObjectMetaclass):
    async def square(self, x):
        return x**2


class ObjectDerived(ObjectBase):
    async def cube(self, x):
        return x**3
```

Note that in the example above, we don't have to use the class decorator on any of the classes.

Context managers
----------------

You can synchronize context manager classes just like any other class and the special methods will be handled properly.

There's also a function decorator `@synchronizer.asynccontextmanager` which behaves just like [https://docs.python.org/3/library/contextlib.html#contextlib.asynccontextmanager](contextlib.asynccontextmanager) but works in both synchronous and asynchronous contexts.


Gotchas
=======

* It works for classes that are context managers, but not for functions returning a context manager
* It creates a new class (with the same name) when wrapping classes, which might lead to typing problems if you have any any un-synchronized usage of the same class
* No idea how this interacts with typing annotations
* If a class is "synchronized", it wraps all the methods on the class, but this typically means you can't reach into attributes and run asynchronous code on it: you might get errors such as "attached to a different loop"
* Note that all synchronized code will run on a different thread, and a different event loop, so calling the code might have some minor extra overhead

TODOs
=====

* Support the opposite case, i.e. you have a blocking function/generator/class/object, and you want to call it asynchronously (this is relatively simple to do for plain functions using [loop.run_in_executor](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor), but Python has no built-in support for generators, and it would be nice to transform a whole class
* More documentation
* Make it possible to annotate methods selectively to return futures
* Maybe make it possible to synchronize objects on the fly, not just classes

This library is limb-amputating edge
====================================

This is code I broke out of a personal projects, and it's not been battle-tested. There is a small test suite that you can run using pytest.
