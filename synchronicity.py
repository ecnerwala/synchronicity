import asyncio
import concurrent.futures
import functools
import inspect
import queue
import threading
import time
import traceback


class Synchronizer:
    '''Helps you offer a blocking (synchronous) interface to asynchronous code.
    '''

    def __init__(self):
        self._loop = None

    def _get_loop(self):
        if self._loop is not None:
            return self._loop

        is_ready = threading.Event()

        def run_forever():
            self._loop = asyncio.new_event_loop()
            is_ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=lambda: run_forever(), daemon=True)
        self._thread.start()
        is_ready.wait()
        return self._loop

    def _is_async_context(self):
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def _make_sync_function(self, coro, return_future):
        loop = self._get_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        if return_future:
            return fut
        else:
            return fut.result()

    def _make_sync_generator(self, coro):
        loop = self._get_loop()
        q = queue.Queue()
        async def pump():
            try:
                async for result in coro:
                    q.put_nowait(('gen', result))
            except Exception as exc:
                traceback.print_exc()
                q.put_nowait(('exc', exc))
            q.put_nowait(('val', None))

        future = asyncio.run_coroutine_threadsafe(pump(), loop)
        while True:
            tag, res = q.get()
            if tag == 'val':
                return res
            elif tag == 'exc':
                raise res
            else:
                yield res

    def _wrap_callable(self, f, return_future=True):
        @functools.wraps(f)
        def f_wrapped(*args, **kwargs):
            res = f(*args, **kwargs)
            if self._is_async_context():
                return res
            elif inspect.iscoroutine(res):
                return self._make_sync_function(res, return_future)
            elif inspect.isasyncgen(res):
                return self._make_sync_generator(res)
            else:
                return res

        return f_wrapped

    def _wrap_class(self, cls):
        new_dict = {}
        cls_name = cls.__name__
        cls_new_name = cls_name + 'Synchronized'
        for k, v in cls.__dict__.items():
            if k == '__aenter__':
                new_dict['__enter__'] = self._wrap_callable(v, return_future=False)
            elif k == '__aexit__':
                new_dict['__exit__'] = self._wrap_callable(v, return_future=False)
            elif callable(v):
                new_dict[k] = self._wrap_callable(v)
            else:
                new_dict[k] = v
        cls_new = type(cls_new_name, tuple(), new_dict)
        return cls_new

    def __call__(self, object):
        if inspect.isclass(object):
            return self._wrap_class(object)
        elif callable(object):
            return self._wrap_callable(object)
        else:
            raise Exception('Argument %s is not a class or a callable' % object)
