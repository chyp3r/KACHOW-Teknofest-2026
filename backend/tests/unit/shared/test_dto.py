import pytest
from app.shared.dto.pagination import PaginationParam, PaginatedResponse

def test_pagination_param():
    p = PaginationParam(page=2, size=10)
    assert p.offset == 10
    assert p.limit == 10
    
    p2 = PaginationParam()
    assert p2.offset == 0
    assert p2.limit == 20

def test_paginated_response():
    resp = PaginatedResponse[str](
        items=["a", "b"],
        total=2,
        page=1,
        size=10,
        pages=1
    )
    assert resp.items == ["a", "b"]
    assert resp.total == 2
    assert resp.page == 1
    assert resp.size == 10
    assert resp.pages == 1
