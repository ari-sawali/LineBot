# TODO: Make system analysis class https://docs.mongodb.com/manual/tutorial/expire-data/

# Deprecating
from .kwdict import (
    kw_dict_mgr, kwdict_col
)

from .groupban import (
    group_ban, gb_col
)

from .msg_track import (
    message_tracker, msg_track_col, msg_event_type
)

# Being prepared to replace
from .group_manage import (
    group_manager, group_data, config_type, user_data
)