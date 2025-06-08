import threading


class RWLock:
    """
    A read-write lock that allows multiple readers but only one writer.
    """
    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
        self._writers = 0
        self._write_waiting = 0

    def read_lock(self):
        """
        Context manager for acquiring a read lock.
        """
        return ReadLockContext(self)

    def write_lock(self):
        """
        Context manager for acquiring a write lock.
        """
        return WriteLockContext(self)

    def _acquire_read(self):
        """
        Acquire a read lock. Multiple threads can hold this type of lock.
        As long as no write lock is held.
        """
        with self._read_ready:
            while self._writers > 0 or self._write_waiting > 0:
                self._read_ready.wait()
            self._readers += 1

    def _release_read(self):
        """
        Release a read lock.
        """
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def _acquire_write(self):
        """
        Acquire a write lock. Only one thread can hold this type of lock.
        """
        with self._read_ready:
            self._write_waiting += 1
            while self._readers > 0 or self._writers > 0:
                self._read_ready.wait()
            self._write_waiting -= 1
            self._writers += 1

    def _release_write(self):
        """
        Release a write lock.
        """
        with self._read_ready:
            self._writers -= 1
            self._read_ready.notify_all()


class ReadLockContext:
    """
    Context manager for read locks.
    """
    def __init__(self, rwlock):
        self.rwlock = rwlock

    def __enter__(self):
        self.rwlock._acquire_read()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.rwlock._release_read()


class WriteLockContext:
    """
    Context manager for write locks.
    """
    def __init__(self, rwlock):
        self.rwlock = rwlock

    def __enter__(self):
        self.rwlock._acquire_write()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.rwlock._release_write()