import hashlib

import json

from typing import Any



 

def sha256_text(value: str) -> str:

    return hashlib.sha256(value.encode("utf-8")).hexdigest()



 

def sha256_json(value: Any) -> str:

    payload = json.dumps(

        value,

        sort_keys=True,

        separators=(",", ":"),

        default=str,

    )

    return sha256_text(payload)


 