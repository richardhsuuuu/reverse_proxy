from collections import OrderedDict
import time

class LRUCache:
    
    """
    A simple implementation of a Least Recently Used (LRU) cache with time-based expiration.

    This LRUCache class uses an OrderedDict to maintain the order of cache entries, ensuring
    that the least recently used items are removed first when the cache exceeds its capacity.
    Each cache entry is associated with a time-to-live (TTL) value, after which the entry is
    considered expired and will be removed upon access.

    Attributes:
        capacity (int): The maximum number of entries the cache can hold. Defaults to 1000.
        TTL (int): The time-to-live for each cache entry in seconds. Defaults to 300 seconds.
        cache (OrderedDict): An ordered dictionary to store cache entries, maintaining access order.
        expiry (dict): A dictionary to track the expiration time of each cache entry.
    """

    def __init__(self, capacity=1000):
        self.cache = OrderedDict()
        self.capacity = capacity
        self.expiry = {}
        self.TTL = 300  # Cache TTL in seconds

    def get(self, key):
        if key in self.cache:
            if time.time() - self.expiry[key] > self.TTL:
                # Remove expired entry
                self.cache.pop(key)
                self.expiry.pop(key) 
                return None
            # Move to end to show recently used
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        self.expiry[key] = time.time()
        if len(self.cache) > self.capacity:
            # Remove least recently used
            oldest = next(iter(self.cache))
            self.cache.popitem(last=False)
            self.expiry.pop(oldest)
