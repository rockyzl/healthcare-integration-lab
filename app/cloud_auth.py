"""Only the Cloud Run gateway may call this private VM service."""
import os
from functools import lru_cache
import requests
import cachecontrol
from google.auth.transport.requests import Request
from google.oauth2 import id_token

@lru_cache(maxsize=1)
def certificate_request():
    return Request(session=cachecontrol.CacheControl(requests.Session()))

def verify_gateway(authorization):
    if not authorization.startswith('Bearer '):
        return False
    try:
        claims = id_token.verify_oauth2_token(authorization[7:], certificate_request(), audience=os.environ['LAB_TOKEN_AUDIENCE'])
        return claims.get('email') == os.environ['LAB_GATEWAY_EMAIL'] and claims.get('email_verified') is True
    except Exception:
        return False
