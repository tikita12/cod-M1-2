class StoreUnavailable(Exception):
    pass


class StoreQuotaExceeded(StoreUnavailable):
    pass


class RecordConflict(Exception):
    pass


class RecordNotFound(Exception):
    pass


class TooManyRecords(Exception):
    pass


class ConversationNotFound(Exception):
    pass


class AIUnavailable(Exception):
    pass
