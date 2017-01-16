from _ast import Tuple, List
from collections import Sequence

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

import selene
import selene.tools
from selene import config
from selene.abctypes.locators import ISeleneWebElementLocator, ISeleneListWebElementLocator
from selene.abctypes.search_context import ISearchContext
from selene.abctypes.webdriver import IWebDriver
from selene.abctypes.webelement import IWebElement
from selene.conditions import Condition, not_
from selene.common.delegation import DelegatingMeta
from selene.helpers import css_or_by_to_by
from selene.support import by
from selene.support.conditions import be
from selene.support.conditions import have
from selene.wait import wait_for

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache


# todo: consider renaming/refactoring to WebDriverWebElementLocator...
class WebDriverWebElementLocator(ISeleneWebElementLocator):
    def __init__(self, by, search_context):
        # type: (Tuple[By, str], ISearchContext) -> None
        self._by = by
        self._search_context = search_context

    @property
    def description(self):
        return 'first_by%s' % str(self._by)

    def find(self):
        return self._search_context.find_element(*self._by)


class InnerWebElementLocator(ISeleneWebElementLocator):
    def __init__(self, by, element):
        # type: (Tuple[By, str], SeleneElement) -> None
        self._by = by
        self._element = element

    @property
    def description(self):
        return "%s.find_by%s" % (self._element, self._by)

    def find(self):
        # return self._element.get_actual_webelement().find_element(*self._by)
        return wait_for(self._element, be.Visible()).find_element(*self._by)


class CachingWebElementLocator(ISeleneWebElementLocator):
    @property
    def description(self):
        return "Caching %s" % (self._element,)

    # todo: will it cash kine of "first wrong webelement"? i.e. invisible element
    @lru_cache()
    def find(self):
        return self._element.get_actual_webelement()

    def __init__(self, element):
        self._element = element


# todo: PyCharm generates abstract methods impl before __init__ method.
# todo: Should we use this order convention? like below...
class IndexedWebElementLocator(ISeleneWebElementLocator):
    def find(self):
        # return self._collection.get_actual_webelements()[self._index]
        return wait_for(self._collection, have.size_at_least(self._index + 1))[self._index]

    @property
    def description(self):
        return "%s[%s]" % (self._collection, self._index)

    def __init__(self, index, collection):
        # type: (int, SeleneCollection) -> None
        self._index = index
        self._collection = collection


class WebdriverListWebElementLocator(ISeleneListWebElementLocator):
    def __init__(self, by, search_context):
        # type: (Tuple[By, str], ISearchContext) -> None
        self._by = by
        self._search_context = search_context

    @property
    def description(self):
        return 'all_by%s' % str(self._by)

    def find(self):
        return self._search_context.find_elements(*self._by)


class InnerListWebElementLocator(ISeleneListWebElementLocator):
    def __init__(self, by, element):
        # type: (Tuple[By, str], SeleneElement) -> None
        self._by = by
        self._element = element

    @property
    def description(self):
        return "(%s).find_all_by(%s)" % (self._element, self._by)

    def find(self):
        # return self._element.get_actual_webelement().find_elements(*self._by)
        return wait_for(self._element, be.Visible()).find_elements(*self._by)


class FilteredListWebElementLocator(ISeleneListWebElementLocator):
    def find(self):
        webelements = self._collection()
        filtered = [webelement
                    for webelement in webelements
                    if self._condition.matches_webelement(webelement)]
        return filtered

    @property
    def description(self):
        return "(%s).filter_by(%s)" % (self._collection, self._condition.description())

    def __init__(self, condition, collection):
        # type: (Condition, SeleneCollection) -> None
        self._condition = condition
        self._collection = collection


class SlicedListWebElementLocator(ISeleneListWebElementLocator):
    def find(self):
        # webelements = self._collection()
        webelements = wait_for(self._collection, have.size_at_least(self._slice.stop))
        return webelements[self._slice.start:self._slice.stop:self._slice.step]

    @property
    def description(self):
        return "(%s)[%s:%s:%s]" % (self._collection, self._slice.start, self._slice.stop, self._slice.step)

    def __init__(self, slc,  collection):
        # type: (slice, SeleneCollection) -> None
        self._slice = slc
        self._collection = collection


class FoundByConditionWebElementLocator(ISeleneWebElementLocator):
    def find(self):
        for webelement in self._collection():
            if self._condition.matches_webelement(webelement):
                return webelement
        raise NoSuchElementException('Element was not found by: %s' % (self._condition,))

    @property
    def description(self):
        return "(%s).select_by(%s)" % (self._collection, self._condition.description())

    def __init__(self, condition, collection):
        # type: (Condition, SeleneCollection) -> None
        self._condition = condition
        self._collection = collection


def _wait_with_screenshot(entity, condition, timeout=None):
    if timeout is None:
        timeout = config.timeout
    try:
        return wait_for(entity, condition, timeout)
    except TimeoutException as e:
        screenshot = selene.tools.take_screenshot()
        msg = '''{original_msg}
        screenshot: {screenshot}'''.format(original_msg=e.msg, screenshot=screenshot)
        raise TimeoutException(msg, e.screen, e.stacktrace)


class SeleneElement(IWebElement):
    __metaclass__ = DelegatingMeta

    @property
    def __delegate__(self):
        # type: () -> IWebElement
        return self._locator.find()

    # todo: is this alias needed?
    def get_actual_webelement(self):
        # type: () -> IWebElement
        return self.__delegate__

    # todo: consider removing this method once conditions will be refactored
    # todo: (currently Condition impl depends on this method)
    def __call__(self):
        return self.__delegate__

    # todo: or... maybe better will be remove __delegate__, and just use __call_ instead... ?

    @classmethod
    def by(cls, by, webdriver, context=None):
        # type: (Tuple[str, str], IWebDriver, ISearchContext) -> SeleneElement
        if not context:
            context = webdriver

        return SeleneElement(WebDriverWebElementLocator(by, context), webdriver)

    @classmethod
    def by_css(cls, css_selector, webdriver, context=None):
        # type: (str, IWebDriver, ISearchContext) -> SeleneElement
        if not context:
            context = webdriver

        return SeleneElement.by((By.CSS_SELECTOR, css_selector), webdriver, context)

    @classmethod
    def by_css_or_by(cls, css_selector_or_by, webdriver, context=None):
        if not context:
            context = webdriver

        return SeleneElement.by(
            css_or_by_to_by(css_selector_or_by),
            webdriver,
            context)

    # todo: consider renaming webdriver to driver, because actually SeleneDriver also can be put here...
    def __init__(self, selene_locator, webdriver):
        # type: (ISeleneWebElementLocator, IWebDriver) -> None
        self._locator = selene_locator
        self._webdriver = webdriver
        self._actions_chains = ActionChains(webdriver)

    def __str__(self):
        return self._locator.description

    def _execute_on_webelement(self, command, condition=be.or_not_to_be):
        return command(_wait_with_screenshot(self, condition))

    # *** Relative elements ***

    def element(self, css_selector_or_by):
        return SeleneElement(
            InnerWebElementLocator(css_or_by_to_by(css_selector_or_by), self),
            self._webdriver)

    s = element
    find = element
    # todo: consider making find a separate not-lazy method (not alias)
    # to be used in such example: s("#element").hover().find(".inner").click()
    #                       over: s("#element").hover().element(".inner").click()
    # todo: should then all action-commands return cached elements by default?

    # todo: this is an object, it does not find. should we switch from method to "as a property" implementation?
    def caching(self):
        return SeleneElement(CachingWebElementLocator(self), self._webdriver)

    # todo: cached or cache?
    def cached(self):
        caching = self.caching()
        return caching.should(be.in_dom)

    def all(self, css_selector_or_by):
        # return SeleneCollection.by_css_or_by(css_selector_or_by, self._webdriver, context=self)
        return SeleneCollection(
            InnerListWebElementLocator(css_or_by_to_by(css_selector_or_by), self),
            self._webdriver)

    ss = all
    elements = all
    find_all = all

    @property
    def parent_element(self):
        return self.element(by.be_parent())

    @property
    def following_sibling(self):
        return self.element(by.be_following_sibling())

    @property
    def first_child(self):
        return self.element(by.be_first_child())

    # *** Asserts (Explicit waits) ***

    def should(self, condition, timeout=None):
        if timeout is None:
            timeout = config.timeout
        # todo: implement proper cashing
        # self._found = wait_for(self, condition, timeout)
        _wait_with_screenshot(self, condition, timeout)
        return self

    # todo: consider removing some aliases
    insist = should
    assure = should
    should_be = should
    should_have = should

    def should_not(self, condition, timeout=None):
        if timeout is None:
            timeout = config.timeout
        # todo: implement proper cashing
        not_condition = not_(condition)
        _wait_with_screenshot(self, not_condition, timeout)
        return self

    # todo: consider removing some aliases
    insist_not = should_not
    assure_not = should_not
    should_not_be = should_not
    should_not_have = should_not

    # *** Additional actions ***

    def double_click(self):
        self._execute_on_webelement(
            lambda it: self._actions_chains.double_click(it).perform(),
            condition=be.Visible())
        return self

    def set(self, new_text_value):

        def clear_and_send_keys(webelement):
            webelement.clear()
            webelement.send_keys(new_text_value)

        self._execute_on_webelement(
            clear_and_send_keys,
            condition=be.Visible())

        return self

    set_value = set

    def press_enter(self):
        return self.send_keys(Keys.ENTER)

    def press_escape(self):
        return self.send_keys(Keys.ESCAPE)

    def press_tab(self):
        return self.send_keys(Keys.TAB)

    def hover(self):
        self._execute_on_webelement(
            lambda it: self._actions_chains.move_to_element(it).perform(),
            condition=be.Visible())
        return self

    # *** ISearchContext methods ***

    def find_elements(self, by=By.ID, value=None):
        return self._execute_on_webelement(
            lambda it: it.find_elements(by, value),
            condition=be.Visible())
        # return self.__delegate__.find_elements(by, value) # todo: remove

    def find_element(self, by=By.ID, value=None):
        return self._execute_on_webelement(
            lambda it: it.find_element(by, value),
            condition=be.Visible())
        # return self.__delegate__.find_element(by, value) # todo: remove

    # *** IWebElement methods ***

    @property
    def tag_name(self):
        return self._execute_on_webelement(
            lambda it: it.tag_name,
            condition=be.in_dom)

    @property
    def text(self):
        return self._execute_on_webelement(
            lambda it: it.text,
            condition=be.Visible())

    def click(self):
        self._execute_on_webelement(
            lambda it: it.click(),
            condition=be.Visible())
        return self  # todo: think on: IWebElement#click was supposed to return None

    def submit(self):
        self._execute_on_webelement(
            lambda it: it.submit(),
            condition=be.Visible())
        return self

    def clear(self):
        self._execute_on_webelement(
            lambda it: it.clear(),
            condition=be.Visible())
        return self

    def get_attribute(self, name):
        return self._execute_on_webelement(
            lambda it: it.get_attribute(name),
            condition=be.in_dom)

    def is_selected(self):
        return self._execute_on_webelement(
            lambda it: it.is_selected(),
            condition=be.Visible())

    def is_enabled(self):
        return self._execute_on_webelement(
            lambda it: it.is_enabled(),
            condition=be.Visible())

    def send_keys(self, *value):
        self._execute_on_webelement(
            lambda it: it.send_keys(*value),
            condition=be.Visible())
        return self

    # RenderedWebElement Items
    def is_displayed(self):
        return self._execute_on_webelement(
            lambda it: it.is_displayed(),
            condition=be.in_dom)

    @property
    def location_once_scrolled_into_view(self):
        return self._execute_on_webelement(
            lambda it: it.location_once_scrolled_into_view,
            condition=be.Visible())

    @property
    def size(self):
        return self._execute_on_webelement(
            lambda it: it.size,
            condition=be.Visible())

    def value_of_css_property(self, property_name):
        return self._execute_on_webelement(
            lambda it: it.value_of_css_property(property_name),
            condition=be.in_dom)

    @property
    def location(self):
        return self._execute_on_webelement(
            lambda it: it.location,
            condition=be.Visible())

    @property
    def rect(self):
        return self._execute_on_webelement(
            lambda it: it.rect,
            condition=be.Visible())

    @property
    def screenshot_as_base64(self):
        return self._execute_on_webelement(
            lambda it: it.screenshot_as_base64,
            condition=be.Visible())  # todo: or `be.in_dom`?

    @property
    def screenshot_as_png(self):
        return self._execute_on_webelement(
            lambda it: it.screenshot_as_png,
            condition=be.Visible())  # todo: or `be.in_dom`?

    def screenshot(self, filename):
        return self._execute_on_webelement(
            lambda it: it.screenshot(filename),
            condition=be.Visible())  # todo: or `be.in_dom`?

    @property
    def parent(self):
        return self._execute_on_webelement(
            lambda it: it.parent,  # todo: should not we return here some Selene entity as search_context?
            condition=be.in_dom)

    @property
    def id(self):
        return self._execute_on_webelement(
            lambda it: it.id,
            condition=be.in_dom)


class SeleneCollection(Sequence):
    """
    To fully match Selenium, SeleneCollection should extend collection.abc.MutableSequence.
    But that's the place where we should be more restrictive.
    It is actually the Selenium, who should use "Sequence" instead of "MutableSequence" (list)
    """

    __metaclass__ = DelegatingMeta

    @property
    def __delegate__(self):
        # type: () -> List[IWebElement]
        return self._locator.find()

    def get_actual_webelements(self):
        # type: () -> List[IWebElement]
        return self.__delegate__

    def __call__(self):
        # type: () -> List[IWebElement]
        return self.__delegate__

    @classmethod
    def by(cls, by, webdriver, context=None):
        # type: (Tuple[str, str], IWebDriver, ISearchContext) -> SeleneCollection
        if not context:
            context = webdriver

        return SeleneCollection(WebdriverListWebElementLocator(by, context), webdriver)

    @classmethod
    def by_css(cls, css_selector, webdriver, context=None):
        # type: (str, IWebDriver, ISearchContext) -> SeleneCollection
        if not context:
            context = webdriver

        return SeleneCollection.by((By.CSS_SELECTOR, css_selector), webdriver, context)

    @classmethod
    def by_css_or_by(cls, css_selector_or_by, webdriver, context=None):
        if not context:
            context = webdriver

        return SeleneCollection.by(css_or_by_to_by(css_selector_or_by), webdriver, context)

    def __init__(self, selene_locator, webdriver):
        # type: (ISeleneListWebElementLocator, IWebDriver) -> None
        self._locator = selene_locator
        self._webdriver = webdriver

    # todo: consider adding self.cashing, self.cashed - like for SeleneElement

    def __str__(self):
        return self._locator.description

    # todo: consider extracting the following not DRY should methods to BaseMixin, or even better: some WaitObject
    # to be mixed in to both Selene Element and Collection
    # Points to think about:
    # * this may break DelegatingMeta logic (because we will have multiple inheritance...)
    # * this will Inheritance... Should not we at least use Composition here?
    def should(self, condition, timeout=None):
        if timeout is None:
            timeout = config.timeout
        _wait_with_screenshot(self, condition, timeout)
        return self

    # todo: consider removing some aliases
    insist = should
    assure = should
    should_be = should
    should_have = should

    def should_not(self, condition, timeout=None):
        if timeout is None:
            timeout = config.timeout
        # todo: implement proper cashing
        not_condition = not_(condition)
        _wait_with_screenshot(self, not_condition, timeout)
        return self

    # todo: consider removing some aliases are even all of them
    insist_not = should_not
    assure_not = should_not
    should_not_be = should_not
    should_not_have = should_not

    def should_each(self, condition, timeout=None):
        if timeout is None:
            timeout = config.timeout

        for selement in self:
            selement.should(condition, timeout)

    def should_each_not(self, condition, timeout=None):
        if timeout is None:
            timeout = config.timeout

        for selement in self:
            selement.should_not(condition, timeout)

    def filtered_by(self, condition):
        return SeleneCollection(FilteredListWebElementLocator(condition, self), self._webdriver)

    ss = filtered_by
    all_by = filtered_by
    filtered = filtered_by
    filter_by = filtered_by
    filterBy = filtered_by

    def element_by(self, condition):
        return SeleneElement(FoundByConditionWebElementLocator(condition, self), self._webdriver)

    s = element_by
    find_by = element_by
    findBy = element_by

    # *** Sequence methods ***

    def __getitem__(self, index):
        if isinstance(index, slice):
            return SeleneCollection(
                SlicedListWebElementLocator(index, collection=self),
                self._webdriver)
        return SeleneElement(IndexedWebElementLocator(index, collection=self), self._webdriver)

    def __len__(self):
        # todo: optimise to the following:
        #   return self.waifFor(size_at_least(0)),
        # where waitFor will return the result of condition application, not self like should
        return len(_wait_with_screenshot(self, have.size_at_least(0)))

    # *** Overriden Sequence methods ***

    def __iter__(self):
        i = 0
        current_len = len(self)
        while i < current_len:
            v = self[i]
            yield v
            i += 1

    # *** Additional Collection style methods ***

    # *** Useful shortcuts ***

    def size(self):
        return len(self)

    def first(self):
        return self[0]
