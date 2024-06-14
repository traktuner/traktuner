#!/usr/bin/python3

import asyncio
import os
import re
import aiohttp
from github_stats import Stats


################################################################################
# Helper Functions
################################################################################

def generate_output_folder() -> None:
    """Create the output folder if it does not already exist"""
    if not os.path.isdir("generated"):
        os.mkdir("generated")

def read_template(file_path: str) -> str:
    """Read and return the content of the template file"""
    with open(file_path, "r") as file:
        return file.read()

def write_output(file_path: str, content: str) -> None:
    """Write content to the specified output file"""
    generate_output_folder()
    with open(file_path, "w") as file:
        file.write(content)

################################################################################
# Individual Image Generation Functions
################################################################################

async def generate_overview(s: Stats, template: str) -> str:
    """Generate SVG content for overview statistics"""
    output = template
    replacements = {
        "{{ name }}": await s.name,
        "{{ stars }}": f"{await s.stargazers:,}",
        "{{ forks }}": f"{await s.forks:,}",
        "{{ contributions }}": f"{await s.total_contributions:,}",
        "{{ lines_changed }}": f"{sum(await s.lines_changed):,}",
        "{{ views }}": f"{await s.views:,}",
        "{{ repos }}": f"{len(await s.repos):,}"
    }
    for key, value in replacements.items():
        output = re.sub(key, value, output)
    return output

async def generate_languages(s: Stats, template: str) -> str:
    """Generate SVG content for languages used"""
    output = template
    progress = ""
    lang_list = ""
    sorted_languages = sorted((await s.languages).items(), reverse=True,
                              key=lambda t: t[1].get("size"))
    delay_between = 150
    for i, (lang, data) in enumerate(sorted_languages):
        color = data.get("color", "#000000")
        progress += (f'<span style="background-color: {color};'
                     f'width: {data.get("prop", 0):0.3f}%;" '
                     f'class="progress-item"></span>')
        lang_list += f"""
<li style="animation-delay: {i * delay_between}ms;">
<svg xmlns="http://www.w3.org/2000/svg" class="octicon" style="fill:{color};"
viewBox="0 0 16 16" version="1.1" width="16" height="16"><path
fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8z"></path></svg>
<span class="lang">{lang}</span>
<span class="percent">{data.get("prop", 0):0.2f}%</span>
</li>
"""
    output = re.sub(r"{{ progress }}", progress, output)
    output = re.sub(r"{{ lang_list }}", lang_list, output)
    return output

################################################################################
# Main Function
################################################################################

async def main() -> None:
    """Generate all badges"""
    access_token = os.getenv("ACCESS_TOKEN")
    user = os.getenv("GITHUB_ACTOR")
    excluded = os.getenv("EXCLUDED")
    excluded = {x.strip() for x in excluded.split(",")} if excluded else None

    try:
        async with aiohttp.ClientSession() as session:
            s = Stats(user, access_token, session, exclude_repos=excluded)
            overview_template = read_template("templates/overview.svg")
            languages_template = read_template("templates/languages.svg")

            overview_content = await generate_overview(s, overview_template)
            languages_content = await generate_languages(s, languages_template)

            write_output("generated/overview.svg", overview_content)
            write_output("generated/languages.svg", languages_content)
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
