import httpx

from offerbench import config

_HEADERS = {
    "content-type": "application/json",
    "origin": "https://leetcode.com",
    "referer": "https://leetcode.com/discuss/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_LIST_QUERY = """
    query discussPostItems($orderBy: ArticleOrderByEnum, $keywords: [String]!, $tagSlugs: [String!], $skip: Int, $first: Int) {
  ugcArticleDiscussionArticles(
    orderBy: $orderBy
    keywords: $keywords
    tagSlugs: $tagSlugs
    skip: $skip
    first: $first
  ) {
    totalNum
    pageInfo {
      hasNextPage
    }
    edges {
      node {
        uuid
        topicId
        title
        slug
        summary
        author {
          realName
          userName
        }
        isAnonymous
        createdAt
        updatedAt
        hitCount
        tags {
          name
          slug
          tagType
        }
      }
    }
  }
}
"""

_DETAIL_QUERY = """
    query discussPostDetail($topicId: ID!) {
  ugcArticleDiscussionArticle(topicId: $topicId) {
    uuid
    topicId
    title
    slug
    summary
    content
    createdAt
    updatedAt
  }
}
"""


class LeetCodeApiError(RuntimeError):
    pass


def _post(query: str, variables: dict, operation_name: str) -> dict:
    response = httpx.post(
        config.LEETCODE_GRAPHQL_URL,
        json={"query": query, "variables": variables, "operationName": operation_name},
        headers={**_HEADERS, "x-operation-name": operation_name},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise LeetCodeApiError(str(body["errors"]))
    return body["data"]


def discuss_post_items(order_by: str, tag_slugs: list[str], skip: int, first: int) -> dict:
    """Returns the raw ugcArticleDiscussionArticles dict:
    {totalNum, pageInfo: {hasNextPage}, edges: [{node: {...}}]}."""
    data = _post(
        _LIST_QUERY,
        {
            "orderBy": order_by,
            "keywords": [""],
            "tagSlugs": tag_slugs,
            "skip": skip,
            "first": first,
        },
        "discussPostItems",
    )
    return data["ugcArticleDiscussionArticles"]


def discuss_post_detail(topic_id: str) -> dict:
    """Returns the raw ugcArticleDiscussionArticle node, including full `content`."""
    data = _post(
        _DETAIL_QUERY, {"topicId": str(topic_id)}, "discussPostDetail"
    )
    return data["ugcArticleDiscussionArticle"]
