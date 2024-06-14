#!/usr/bin/python3

import asyncio
import os
from typing import Dict, List, Optional, Set, Tuple

import aiohttp
import requests

###############################################################################
# Main Classes
###############################################################################

class Queries:
    """
    Class with functions to query the GitHub GraphQL (v4) API and the REST (v3) API.
    Also includes functions to dynamically generate GraphQL queries.
    """

    def __init__(self, username: str, access_token: str, session: aiohttp.ClientSession, max_connections: int = 10):
        self.username = username
        self.access_token = access_token
        self.session = session
        self.semaphore = asyncio.Semaphore(max_connections)

    async def query(self, generated_query: str) -> Dict:
        """
        Make a request to the GraphQL API using the authentication token.
        :param generated_query: string query to be sent to the API
        :return: decoded GraphQL JSON output
        """
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with self.semaphore:
            async with self.session.post("https://api.github.com/graphql", headers=headers, json={"query": generated_query}) as response:
                if response.status != 200:
                    print(f"GraphQL query failed with status {response.status}")
                return await response.json()

    async def query_rest(self, path: str, params: Optional[Dict] = None) -> Dict:
        """
        Make a request to the REST API.
        :param path: API path to query
        :param params: Query parameters to be passed to the API
        :return: deserialized REST JSON output
        """
        headers = {"Authorization": f"token {self.access_token}"}
        params = params or {}

        for _ in range(60):
            async with self.semaphore:
                async with self.session.get(f"https://api.github.com/{path.lstrip('/')}", headers=headers, params=params) as response:
                    if response.status == 202:
                        print("Received 202. Retrying...")
                        await asyncio.sleep(2)
                        continue
                    return await response.json()

        print(f"Too many retries for {path}. Data will be incomplete.")
        return {}

    @staticmethod
    def repos_overview(contrib_cursor: Optional[str] = None, owned_cursor: Optional[str] = None) -> str:
        """
        Generate a GraphQL query to get an overview of user repositories.
        :return: GraphQL query string
        """
        return f"""{{
  viewer {{
    login,
    name,
    repositories(first: 100, orderBy: {{field: UPDATED_AT, direction: DESC}}, isFork: false, after: {"null" if owned_cursor is None else f'"{owned_cursor}"'}) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      nodes {{
        nameWithOwner
        stargazers {{
          totalCount
        }}
        forkCount
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{
            size
            node {{
              name
              color
            }}
          }}
        }}
      }}
    }}
    repositoriesContributedTo(first: 100, includeUserRepositories: false, orderBy: {{field: UPDATED_AT, direction: DESC}}, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW], after: {"null" if contrib_cursor is None else f'"{contrib_cursor}"'}) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      nodes {{
        nameWithOwner
        stargazers {{
          totalCount
        }}
        forkCount
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{
            size
            node {{
              name
              color
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""

    @staticmethod
    def contrib_years() -> str:
        """
        Generate a GraphQL query to get all years the user has been a contributor.
        :return: GraphQL query string
        """
        return """
query {
  viewer {
    contributionsCollection {
      contributionYears
    }
  }
}
"""

    @staticmethod
    def contribs_by_year(year: str) -> str:
        """
        Generate a GraphQL query to get contributions for a specific year.
        :param year: year to query for
        :return: GraphQL query string
        """
        return f"""
    year{year}: contributionsCollection(from: "{year}-01-01T00:00:00Z", to: "{int(year) + 1}-01-01T00:00:00Z") {{
      contributionCalendar {{
        totalContributions
      }}
    }}
"""

    @classmethod
    def all_contribs(cls, years: List[str]) -> str:
        """
        Generate a GraphQL query to get contributions for all specified years.
        :param years: list of years to get contributions for
        :return: GraphQL query string
        """
        by_years = "\n".join(map(cls.contribs_by_year, years))
        return f"""
query {{
  viewer {{
    {by_years}
  }}
}}
"""


class Stats:
    """
    Retrieve and store statistics about GitHub usage.
    """

    def __init__(self, username: str, access_token: str, session: aiohttp.ClientSession, exclude_repos: Optional[Set[str]] = None):
        self.username = username
        self._exclude_repos = exclude_repos or set()
        self.queries = Queries(username, access_token, session)
        self._name: Optional[str] = None
        self._stargazers: Optional[int] = None
        self._forks: Optional[int] = None
        self._total_contributions: Optional[int] = None
        self._languages: Optional[Dict] = None
        self._repos: Optional[Set[str]] = None
        self._lines_changed: Optional[Tuple[int, int]] = None
        self._views: Optional[int] = None

    async def to_str(self) -> str:
        """
        :return: summary of all available statistics
        """
        languages = await self.languages_proportional
        formatted_languages = "\n  - ".join([f"{k}: {v:.4f}%" for k, v in languages.items()])
        lines_changed = await self.lines_changed
        return f"""Name: {await self.name}
Stargazers: {await self.stargazers:,}
Forks: {await self.forks:,}
All-time contributions: {await self.total_contributions:,}
Repositories with contributions: {len(await self.repos)}
Lines of code added: {lines_changed[0]:,}
Lines of code deleted: {lines_changed[1]:,}
Lines of code changed: {lines_changed[0] + lines_changed[1]:,}
Project page views: {await self.views:,}
Languages:
  - {formatted_languages}"""

    async def get_stats(self) -> None:
        """
        Get lots of summary statistics using one big query. Sets many attributes
        """
        self._stargazers = 0
        self._forks = 0
        self._languages = {}
        self._repos = set()

        next_owned = None
        next_contrib = None
        while True:
            raw_results = await self.queries.query(Queries.repos_overview(owned_cursor=next_owned, contrib_cursor=next_contrib))
            viewer = raw_results.get("data", {}).get("viewer", {})

            self._name = viewer.get("name", viewer.get("login", "No Name"))

            contrib_repos = viewer.get("repositoriesContributedTo", {})
            owned_repos = viewer.get("repositories", {})
            repos = contrib_repos.get("nodes", []) + owned_repos.get("nodes", [])

            for repo in repos:
                name = repo.get("nameWithOwner")
                if name in self._repos or name in self._exclude_repos:
                    continue
                self._repos.add(name)
                self._stargazers += repo.get("stargazers", {}).get("totalCount", 0)
                self._forks += repo.get("forkCount", 0)

                for lang in repo.get("languages", {}).get("edges", []):
                    lang_name = lang.get("node", {}).get("name", "Other")
                    lang_size = lang.get("size", 0)
                    lang_color = lang.get("node", {}).get("color")
                    if lang_name in self._languages:
                        self._languages[lang_name]["size"] += lang_size
                        self._languages[lang_name]["occurrences"] += 1
                    else:
                        self._languages[lang_name] = {"size": lang_size, "occurrences": 1, "color": lang_color}

            if owned_repos.get("pageInfo", {}).get("hasNextPage", False) or contrib_repos.get("pageInfo", {}).get("hasNextPage", False):
                next_owned = owned_repos.get("pageInfo", {}).get("endCursor", next_owned)
                next_contrib = contrib_repos.get("pageInfo", {}).get("endCursor", next_contrib)
            else:
                break

        langs_total = sum(v["size"] for v in self._languages.values())
        for k, v in self._languages.items():
            v["prop"] = 100 * (v["size"] / langs_total)

    @property
    async def name(self) -> str:
        if self._name is None:
            await self.get_stats()
        return self._name

    @property
    async def stargazers(self) -> int:
        if self._stargazers is None:
            await self.get_stats()
        return self._stargazers

    @property
    async def forks(self) -> int:
        if self._forks is None:
            await self.get_stats()
        return self._forks

    @property
    async def languages(self) -> Dict:
        if self._languages is None:
            await self.get_stats()
        return self._languages

    @property
    async def languages_proportional(self) -> Dict:
        if self._languages is None:
            await self.get_stats()
        return {k: v["prop"] for k, v in self._languages.items()}

    @property
    async def repos(self) -> Set[str]:
        if self._repos is None:
            await self.get_stats()
        return self._repos

    @property
    async def total_contributions(self) -> int:
        if self._total_contributions is None:
            self._total_contributions = 0
            years = (await self.queries.query(Queries.contrib_years())).get("data", {}).get("viewer", {}).get("contributionsCollection", {}).get("contributionYears", [])
            by_year = (await self.queries.query(Queries.all_contribs(years))).get("data", {}).get("viewer", {}).values()
            for year in by_year:
                self._total_contributions += year.get("contributionCalendar", {}).get("totalContributions", 0)
        return self._total_contributions

    @property
    async def lines_changed(self) -> Tuple[int, int]:
        if self._lines_changed is None:
            additions = 0
            deletions = 0
            for repo in await self.repos:
                r = await self.queries.query_rest(f"/repos/{repo}/stats/contributors")
                for author_obj in r:
                    if author_obj.get("author", {}).get("login") == self.username:
                        for week in author_obj.get("weeks", []):
                            additions += week.get("a", 0)
                            deletions += week.get("d", 0)
            self._lines_changed = (additions, deletions)
        return self._lines_changed

    @property
    async def views(self) -> int:
        if self._views is None:
            total = 0
            for repo in await self.repos:
                r = await self.queries.query_rest(f"/repos/{repo}/traffic/views")
                total += sum(view.get("count", 0) for view in r.get("views", []))
            self._views = total
        return self._views


###############################################################################
# Main Function
###############################################################################

async def main() -> None:
    """
    Used mostly for testing; this module is not usually run standalone
    """
    access_token = os.getenv("ACCESS_TOKEN")
    user = os.getenv("GITHUB_ACTOR")
    async with aiohttp.ClientSession() as session:
        s = Stats(user, access_token, session)
        print(await s.to_str())

if __name__ == "__main__":
    asyncio.run(main())
