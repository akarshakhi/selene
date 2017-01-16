import selene
import selene.tools
from selene import config
from selene.conditions import not_

__author__ = 'yashaka'

import time
from selenium.common.exceptions import TimeoutException


def wait_for(entity, method, timeout=None, message=None):
    if message is None:
        message = method  # todo: refactor
    if not timeout:
        timeout = config.timeout
    end_time = time.time() + timeout
    while True:
        try:
            return method(entity)
        except Exception as reason:
            reason_message = getattr(reason, 'msg', getattr(reason, 'message', ''))
            reason_string = '{name}: {message}'.format(name=reason.__class__.__name__, message=reason_message)
            screen = getattr(reason, 'screen', None)
            stacktrace = getattr(reason, 'stacktrace', None)

            if time.time() > end_time:
                raise TimeoutException('''
            failed while waiting {timeout} seconds
            to assert {condition}
            {message}

            reason: {reason}'''.format(
                    timeout=timeout,
                    condition=method.description(),
                    message=message,
                    reason=reason_string), screen, stacktrace)

            time.sleep(config.poll_during_waits)


def has(entity, method):
    try:
        value = method(entity)
        return value if value is not None else False
    except Exception as exc:
        return False


def has_not(entity, method):
    return has(entity, not_(method))
