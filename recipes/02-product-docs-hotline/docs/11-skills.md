# Skills

A skill is a packaged capability you add to an agent with one line. A skill registers its own tools and can add a section to the prompt.

```python
agent.add_skill("datetime")
agent.add_skill("native_vector_search", {"tool_name": "search_docs",
                                         "index_file": "data/knowledge.swsearch"})
```

Built-in skills include date and time, math, web search, Wikipedia search, DataSphere search and native vector search. Some skills need an API key for an outside service. The native vector search skill needs no outside account.

Most skills accept a `tool_name`, so you can add the same skill twice with different names, for example two search tools over two different indexes.

You can write your own skill by extending `SkillBase`, giving it a `SKILL_NAME`, and registering its tools in `register_tools`. Register the class with `register_skill`, then add it like any built-in skill.

Set `skip_prompt` to true if you want to write the prompt instructions for a skill yourself.
