"""Every def has zero annotations: expected 0% on both metrics."""


def plain(x, y):
    return x + y


def no_args():
    pass


def varargs(*args, **kwargs):
    return args


async def async_fn(x):
    return x


class MyClass:
    def method(self, x):
        return x

    def another(self):
        return 1
