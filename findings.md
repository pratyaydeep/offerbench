# LeetCode Discuss GraphQL API — Findings

## Endpoint

`POST https://leetcode.com/graphql/`

Single GraphQL endpoint. Operation is selected via the `operationName` field in
the body (and conventionally mirrored in an `x-operation-name` header, though
that header isn't required by GraphQL itself).

## Auth: none required

Tested with **zero cookies and no `authorization` header** — still returns
`200` with full data. This query is public/unauthenticated/read-only.

The original captured curl had a full browser cookie jar (`cf_clearance`,
`csrftoken`, session ids, ad/analytics cookies, etc.) but none of it was
necessary for this query.

### Why a CSRF token shows up even when never logged in

Django's `CsrfViewMiddleware` issues a `csrftoken` cookie to anonymous
visitors too, not just authenticated sessions — confirmed directly: a request
sent with no cookies at all came back with:

```
set-cookie: csrftoken=Fct9Ja8WSbeM8po1IJh74Td4Wfo9UrDC; expires=...; Path=/; SameSite=Lax; Secure
```

The browser picks this up on an earlier anonymous page load, JS reads it back
out of the cookie, and echoes it into the `x-csrftoken` request header
(the standard Django "double-submit cookie" CSRF pattern). It has nothing to
do with login state.

## Query: `discussPostItems`

Fetches paginated discuss/forum posts (e.g. salary/compensation discussion
threads).

### Variables

```json
{
  "orderBy": "HOT",              // ArticleOrderByEnum — HOT seen; likely also NEWEST/MOST_VOTES etc.
  "keywords": [""],              // search keywords; [""] = no filter
  "tagSlugs": ["compensation"],  // filter by tag slug
  "skip": 0,                     // pagination offset
  "first": 50                    // page size
}
```

### Root field

`ugcArticleDiscussionArticles(orderBy, keywords, tagSlugs, skip, first)`:

- `totalNum` — total count matching the filter
- `pageInfo.hasNextPage` — pagination flag
- `edges[].node` — post objects (Relay-shaped, but pagination is plain
  `skip`/`first`, not cursor-based — no `cursor` field requested/used)

### Node fields available

- Identity: `uuid`, `slug`, `topicId`, `title`, `summary`
- Author: nested object — `realName`, `userSlug`, `userName`, `nameColor`,
  `certificationLevel`, `activeBadge { icon, displayName }`
- Flags: `isOwner`, `isAnonymous`, `isSerialized`, `isLeetcode`, `canSee`,
  `canEdit`, `isMyFavorite`, `myReactionType`
- Engagement: `hitCount` (views), `reactions[] { count, reactionType }`
  (e.g. `UPVOTE`), `topic { id, topLevelCommentCount }`
- Metadata: `createdAt`, `updatedAt`, `status` (e.g. `OPEN`), `articleType`
  (e.g. `DISCUSSION`), `tags[] { name, slug, tagType }`

## Query: `discussPostDetail`

Fetches the full detail of a single post, given its `topicId` (the numeric
id returned as `topicId`/`topic.id` in `discussPostItems`).

### Variables

```json
{ "topicId": "8342974" }
```

(`topicId` is typed `ID!` in the schema — a string works even though the
underlying value is numeric.)

### Root field

`ugcArticleDiscussionArticle(topicId)` — same shape as a `discussPostItems`
node, plus:

- **`content`** — the full, untruncated post body (the list query only
  exposes `summary`, a truncated preview of the same text)
- `isSlate` — whether the body is in Slate.js rich-text format
- `isBlockComments`, `isAuthorArticleReviewer` — extra moderation/author flags
  not present on the list node

Verified example (`topicId: 8342974`, the Teradata post): `summary` was
truncated mid-sentence ("...lowball but recru"), `content` had the full text
including the trailing question ("...considering my experience. Any
thoughts?").

Also tested with **zero cookies/auth** — `200`, full data returned. Same as
`discussPostItems`, this is a public unauthenticated read.

## Query: `questionDiscussComments`

Fetches comments on a post, given its `topicId`.

### Variables

```json
{
  "topicId": 8342974,           // Int! here (note: Int, not ID like discussPostDetail)
  "pageNo": 1,                  // 1-indexed page number
  "numPerPage": 10,             // page size
  "orderBy": "best"             // also seen as default "newest_to_oldest" in the query signature
}
```

### Root field

`topicComments(topicId, orderBy, pageNo, numPerPage)`:

- `totalNum` — total top-level comment count (matches `topic.topLevelCommentCount`
  from `discussPostItems`/`discussPostDetail`)
- `data[]` — comment wrapper objects:
  - `id`, `ipRegion`, `pinned`, `pinnedBy { username }`, `intentionTag { slug }`
  - `numChildren` — count of nested replies under this comment
  - `post { ...DiscussPost }` — the actual comment content (named `post`,
    reusing the underlying `PostNode` type that backs top-level discuss posts
    too)

### `DiscussPost` fragment (on `PostNode`)

- `id`, `content`, `voteCount`, `voteUpCount`, `voteStatus`
- `creationDate`, `updationDate` (unix timestamps, not ISO strings — unlike
  `createdAt`/`updatedAt` elsewhere), `status`, `isHidden`, `anonymous`
- `author { isDiscussAdmin, isDiscussStaff, username, nameColor, activeBadge { displayName, icon }, profile { userAvatar, reputation, realName, certificationLevel }, isActive }`
- `authorIsModerator`, `isOwnPost`, `isSerialized`

### Verified behavior

- Also fully **unauthenticated** — `200` with real data, no cookies sent.
- `numPerPage`/`pageNo` paginate **top-level comments only**.
- When a comment has `numChildren > 0`, its replies are **not** included in
  this response — they need a separate call (not yet captured/tested; likely
  a sibling query taking a parent comment id, analogous to how this query
  takes `topicId`).
- Example (`topicId: 8328175`, "Received offer from Booking holdings"):
  `totalNum: 12` (top-level), one comment had `numChildren: 2` (its replies
  weren't returned here).

## Pagination behavior (verified)

Tested `tagSlugs: ["compensation"]` with `totalNum: 3000`:

| skip  | result                                      |
|-------|----------------------------------------------|
| 0     | first 5 posts, `hasNextPage: true`            |
| 50    | next distinct 5 posts, `hasNextPage: true`    |
| 100   | distinct, `hasNextPage: true`                 |
| 1000  | distinct, `hasNextPage: true`                 |
| 2950  | distinct, `hasNextPage: true`                 |
| 3000  | empty `edges`, `hasNextPage: false`           |
| 3050  | empty `edges`, `hasNextPage: false` (no error)|
| 5000  | empty `edges`, `hasNextPage: false` (no error)|

Conclusions:

- Plain offset pagination (`skip`/`first`) works cleanly across the whole
  result set, returning sequential non-overlapping pages.
- Going past `totalNum` does **not** error — it just returns empty results.
  Safe to loop until `edges` is empty or `pageInfo.hasNextPage` is `false`.
- Full-scrape loop: `skip = 0, 50, 100, ...` with `first=50` (untested
  whether larger `first` values, e.g. 100/200, are accepted — worth probing
  to reduce request count).

## Operational notes

- No auth/cookies needed for this query, but it's still unauthenticated
  scraping at volume (3000+ posts for just one tag) — pace requests (e.g.
  ~1s between calls) to avoid Cloudflare/rate-limit triggers, since that's
  presumably what `cf_clearance` is for under heavier load or other endpoints.
