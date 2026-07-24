<!-- TEMPLATE-ONLY
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  This is the TEMPLATE.  README.md is generated from it:                  │
  │                                                                          │
  │      python build.py                                                     │
  │                                                                          │
  │  Edit this file, never README.md.                                        │
  │                                                                          │
  │  Double-brace tokens are substituted at build time — see                 │
  │  build_readme_tokens() in build.py for the full list.  Asset tokens       │
  │  (HERO_SVG, TERMINAL_SVG, INFO_SVG, CONTRIBUTION_SVG) resolve to relative │
  │  paths with a content hash appended, so GitHub's image proxy always       │
  │  serves the freshly generated file.                                      │
  │                                                                          │
  │  This comment block is stripped from the rendered README.                │
  └──────────────────────────────────────────────────────────────────────────┘
TEMPLATE-ONLY -->

<div align="center">

<img src="{{HERO_SVG}}" alt="{{DISPLAY_NAME}} — {{TAGLINE}}" width="100%">

</div>

<h1 align="center">{{DISPLAY_NAME}}</h1>
<p align="center"><em>{{TAGLINE}}</em></p>

<p align="center">
  <a href="https://github.com/{{USERNAME}}?tab=repositories"><img src="https://img.shields.io/badge/repositories-{{REPO_COUNT}}-22d3ee?style=flat-square&labelColor=161b22" alt="{{REPO_COUNT}} public repositories"></a>
  <a href="https://github.com/{{USERNAME}}"><img src="https://img.shields.io/badge/contributions-{{CONTRIBUTION_COUNT}}-3fb950?style=flat-square&labelColor=161b22" alt="{{CONTRIBUTION_COUNT}} contributions"></a>
  <a href="https://github.com/{{USERNAME}}?tab=followers"><img src="https://img.shields.io/badge/followers-{{FOLLOWER_COUNT}}-a78bfa?style=flat-square&labelColor=161b22" alt="{{FOLLOWER_COUNT}} followers"></a>
  <img src="https://img.shields.io/badge/since-{{MEMBER_SINCE}}-f0883e?style=flat-square&labelColor=161b22" alt="Member since {{MEMBER_SINCE}}">
</p>

<br>

<div align="center">
  <table>
    <tr>
      <td width="50%" valign="top">
        <img src="{{TERMINAL_SVG}}" alt="ASCII portrait of @{{USERNAME}} typing itself into a terminal" width="100%">
      </td>
      <td width="50%" valign="top">
        <img src="{{INFO_SVG}}" alt="Profile summary card: about, stack and highlights" width="100%">
      </td>
    </tr>
  </table>
</div>

<br>

<div align="center">

<img src="{{CONTRIBUTION_SVG}}" alt="Animated contribution calendar — {{CONTRIBUTION_COUNT}} contributions, {{ACTIVE_DAYS}} active days" width="100%">

</div>

<br>

<div align="center">

**{{ACTIVE_DAYS}}** active days &nbsp;·&nbsp; **{{LONGEST_STREAK}}** longest streak &nbsp;·&nbsp; **{{CURRENT_STREAK}}** current streak &nbsp;·&nbsp; **{{TOP_LANGUAGE}}** most used

</div>

<br>

<div align="center">
  <sub>
    Every asset above is a standalone animated SVG — no JavaScript, no external CSS, no web fonts.<br>
    Generated with <a href="https://github.com/{{USERNAME}}">this repository's</a> Python build:
    <code>python build.py</code> &nbsp;·&nbsp; last run {{GENERATED_AT}}
  </sub>
</div>
