"""
Authentication utilities for gateway architecture.

This module provides FastAPI dependencies for extracting user context from
TRUSTED headers set by the Next.js gateway layer.

SECURITY MODEL:
--------------
FastAPI does NOT verify JWT signatures or validate sessions.
All authentication happens at the Next.js layer.

Next.js validates NextAuth sessions and sets these headers:
  - X-Business-User-Id
  - X-Org-Id
  - X-User-Role

FastAPI trusts these headers because:
  1. FastAPI is NOT publicly accessible (private network only)
  2. Only Next.js server can reach FastAPI
  3. Browser cannot send requests directly to FastAPI

PRODUCTION DEPLOYMENT REQUIREMENTS:
-----------------------------------
  - FastAPI must run in a private network (VPC / Docker internal network)
  - Firewall rules must prevent direct public access to FastAPI
  - Only Next.js should be able to reach FastAPI (port 8000)
  - Next.js is the authentication boundary

INCORRECT DEPLOYMENTS (Security Risk):
--------------------------------------
  ❌ FastAPI exposed to public internet
  ❌ Browser making direct requests to FastAPI
  ❌ Multiple untrusted clients accessing FastAPI
"""

from fastapi import Header, HTTPException
from typing import Optional
from pydantic import BaseModel


class UserContext(BaseModel):
    """Business user context extracted from trusted Next.js gateway headers."""
    business_user_id: str
    org_id: str
    role: str


def get_user_context(
    business_user_id: Optional[str] = Header(None, alias='x-business-user-id'),
    org_id: Optional[str] = Header(None, alias='x-org-id'),
    user_role: Optional[str] = Header(None, alias='x-user-role'),
) -> UserContext:
    """
    FastAPI dependency to extract user context from TRUSTED gateway headers.
    
    This dependency assumes requests come from Next.js gateway only.
    Next.js validates NextAuth sessions and forwards user context via headers.
    
    Usage:
        @router.get("/invoices")
        def list_invoices(user_ctx: UserContext = Depends(get_user_context)):
            # user_ctx contains validated user information from Next.js
            pass
    
    Args:
        business_user_id: X-Business-User-Id header (set by Next.js after session validation)
        org_id: X-Org-Id header (set by Next.js after session validation)
        user_role: X-User-Role header (set by Next.js after session validation)
        
    Returns:
        UserContext with business user information
        
    Raises:
        HTTPException: If required headers are missing (indicates misconfigured gateway)
    """
    if not business_user_id or not org_id:
        raise HTTPException(
            status_code=401,
            detail='Authentication required - missing user context headers from gateway'
        )
    
    return UserContext(
        business_user_id=business_user_id,
        org_id=org_id,
        role=user_role or 'user',
    )

