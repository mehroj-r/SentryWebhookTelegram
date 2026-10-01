from datetime import timedelta


async def test_seen_add_if_new_is_atomic(repos):
    assert await repos.seen.add_if_new("r1") is True
    assert await repos.seen.add_if_new("r1") is False
    assert await repos.seen.exists("r1")


async def test_seen_purge(repos):
    await repos.seen.add_if_new("old")
    # Nothing is older than 1 day yet
    assert await repos.seen.purge_older_than(timedelta(days=1)) == 0
    # Everything is older than "minus one day" (cutoff in the future)
    assert await repos.seen.purge_older_than(timedelta(days=-1)) == 1
    assert not await repos.seen.exists("old")


async def test_route_add_dedup_and_null_env(repos):
    assert await repos.routes.add("p", None, 100) is True
    assert await repos.routes.add("p", None, 100) is False
    assert await repos.routes.add("p", "prod", 100) is True
    assert await repos.routes.add("p", "prod", 100) is False


async def test_route_remove_scoped_to_chat(repos):
    await repos.routes.add("p", None, 100)
    [route] = await repos.routes.list_for_chat(100)
    # another chat cannot delete it
    assert await repos.routes.remove(route["id"], 200) is False
    assert len(await repos.routes.list_for_chat(100)) == 1
    assert await repos.routes.remove(route["id"], 100) is True
    assert await repos.routes.list_for_chat(100) == []


async def test_resolve_chats_exact_then_wildcard_then_all(repos):
    await repos.routes.add("p", "prod", 1)
    await repos.routes.add("p", None, 2)
    await repos.routes.add("p", "staging", 3)

    assert await repos.routes.resolve_chats("p", "prod") == [1]
    # unknown env → wildcard only
    assert await repos.routes.resolve_chats("p", "dev") == [2]
    # env not provided by Sentry → every subscriber of the project
    assert sorted(await repos.routes.resolve_chats("p", None)) == [1, 2, 3]
    assert await repos.routes.resolve_chats("other", None) == []


async def test_project_upsert_preserves_values(repos):
    await repos.projects.upsert("p", ref_id=5, name="Proj")
    await repos.projects.upsert("p", ref_id=None, name=None)
    assert await repos.projects.list_all() == [{"slug": "p", "ref_id": 5, "name": "Proj"}]
    assert await repos.projects.slug_for_ref_id(5) == "p"
