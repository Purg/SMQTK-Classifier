from threading import RLock
from typing import Any, Dict, Hashable, Optional

from smqtk_classifier.exceptions import NoClassificationError
from smqtk_classifier.interfaces.classification_element import (
    ClassificationElement, CLASSIFICATION_MAP_T, CLASSIFICATION_DICT_T
)


class MemoryClassificationElement (ClassificationElement):  # lgtm [py/missing-equals]
    """
    In-memory representation of classification results. This is represented
    with a python dictionary.

    :param type_name: Name of the type of classifier this classification
        was generated by.
    :type type_name: str

    :param uuid: Unique ID reference of the classification
    :type uuid: collections.abc.Hashable
    """

    __slots__ = ('_c', '_c_lock')

    def __init__(self, type_name: str, uuid: Hashable):
        super(MemoryClassificationElement, self).__init__(type_name, uuid)

        # dictionary of classification labels and values
        self._c: Optional[CLASSIFICATION_DICT_T] = None
        # Cannot be pickled. New lock initialized upon pickle/unpickle
        self._c_lock = RLock()

    @classmethod
    def is_usable(cls) -> bool:
        # No external dependencies
        return True

    def get_config(self) -> Dict[str, Any]:
        return {}

    def __getstate__(self) -> Any:
        state = {
            'parent': super(MemoryClassificationElement, self).__getstate__(),
        }
        with self._c_lock:
            state['c'] = self._c
        return state

    def __setstate__(self, state: Any) -> None:
        super(MemoryClassificationElement, self).__setstate__(state['parent'])
        if not hasattr(self, '_c_lock') or self._c_lock is None:
            self._c_lock = RLock()
        with self._c_lock:
            #: :type: None | dict[collections.abc.Hashable, float]
            self._c = state['c']

    def has_classifications(self) -> bool:
        with self._c_lock:
            return bool(self._c)

    def get_classification(self) -> CLASSIFICATION_DICT_T:
        with self._c_lock:
            if self._c:
                return self._c
            else:
                raise NoClassificationError("No classification labels/values")

    def set_classification(
        self,
        m: Optional[CLASSIFICATION_MAP_T] = None,
        **kwds: float
    ) -> CLASSIFICATION_DICT_T:
        m = super(MemoryClassificationElement, self)\
            .set_classification(m, **kwds)
        with self._c_lock:
            self._c = m
        return m
