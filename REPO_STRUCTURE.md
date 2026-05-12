# Autonomous Blogger Pipeline — Repository Structure

```
autonomous-blogger/
├── .github/
│   └── workflows/
│       ├── daily_pipeline.yml          # Main daily content pipeline
│       ├── weekly_improvement.yml      # Self-improvement agent
│       └── monthly_expansion.yml       # Genre expansion agent
│
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py                 # Agent 1: Orchestrator
│   ├── topic_discovery.py              # Agent 2: Topic Discovery
│   ├── research.py                     # Agent 3: Research
│   ├── content_generation.py           # Agent 4: Content Generation
│   ├── reference_citation.py           # Agent 5: Reference & Citation
│   ├── seo.py                          # Agent 6: SEO
│   ├── image_agent.py                  # Agent 7: Image
│   ├── video_agent.py                  # Agent 8: Video
│   ├── publisher.py                    # Agent 9: Publisher
│   └── self_improvement.py             # Agent 10: Self-Improvement
│
├── config/
│   ├── settings.py                     # Central config loader
│   ├── tone_profiles.json              # Genre tone profiles
│   ├── section_templates.json          # Layer section templates
│   └── quota_state.json                # Runtime quota tracker (gitignored)
│
├── taxonomy/
│   ├── taxonomy.json                   # Full genre/topic/layer taxonomy
│   └── taxonomy_changelog.json         # Version history of taxonomy changes
│
├── prompts/
│   ├── news_prompt.txt
│   ├── research_prompt.txt
│   ├── howto_prompt.txt
│   ├── opinion_prompt.txt
│   ├── casestudy_prompt.txt
│   ├── interview_prompt.txt
│   ├── listicle_prompt.txt
│   ├── review_prompt.txt
│   ├── explainer_prompt.txt
│   └── video_decision_prompt.txt
│
├── templates/
│   ├── blogger_template.xml            # Full Blogger XML theme
│   ├── post_html_template.html         # HTML shell for assembled posts
│   └── genre_landing_page.html         # Auto-generated genre landing page
│
├── logs/
│   ├── published_posts.json            # Post log (URL, metadata, date)
│   ├── quota_log.json                  # Daily API usage log
│   └── pipeline_runs.json             # Run history
│
├── utils/
│   ├── gemini_client.py                # Gemini API wrapper + rate limiting
│   ├── blogger_client.py               # Blogger API v3 wrapper
│   ├── firebase_client.py              # Firebase Admin SDK wrapper
│   ├── link_validator.py               # HTTP HEAD checker + archive fallback
│   ├── dedup_checker.py                # Duplicate post detection
│   ├── rss_fetcher.py                  # Google Trends + Reddit RSS
│   └── quota_manager.py               # Quota tracker + backoff logic
│
├── tests/
│   ├── test_agents.py
│   ├── test_utils.py
│   └── fixtures/
│       └── sample_research_brief.json
│
├── docs/
│   ├── DEPLOYMENT_CHECKLIST.md        # [M] Step-by-step setup guide
│   ├── BLOGGER_SETUP.md               # [F] Blogger API + OAuth guide
│   ├── FIREBASE_SETUP.md              # [H] Firebase like counter guide
│   └── DISQUS_SETUP.md                # [I] Disqus comment system guide
│
├── sample_output/
│   └── sample_post.html               # [N] Full sample post output
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```
