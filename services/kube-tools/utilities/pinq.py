def select(items, func):
    results = []
    for item in items:
        results.append(func(item))

    return results


def where(items, func):
    results = []
    for item in items:
        if func(item) is True:
            results.append(item)
    return results


def first(items, func=None):
    for item in items:
        if not func:
            return item
        if func(item):
            return item


def any(items, func):
    for item in items:
        if func(item):
            return True
    return False
