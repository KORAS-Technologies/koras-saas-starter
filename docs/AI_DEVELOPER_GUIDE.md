# AI Developer Guide — how a generated product uses the assistant

> Scope: a product generated from `koras-saas-starter` with the `ai`
> capability. Every example is generic; the starter names no product's
> entities and this guide invents none. `docs/AI_ARCHITECTURE.md` says what
> the pieces are; this says what to do with them.

## Enabling AI

At generation, with the gateway it needs:

```bash
pnpm create-koras-app <slug> --profile product --output-dir <parent> --with ai,ai_gateway
```

`ai` without `ai_gateway` is refused with the flag to pass. A project that
already exists is brought up with the generator's refresh, naming the paths
the capability gates; the list is `template_map` under `capabilities` in
`profiles/product/manifest.yaml`.

Then, per environment, the gateway's settings in Doppler: the provider keys
and the master key. `AI_GATEWAY_URL` is derived from Terraform. Locally,
`local/config/.env.local.example` shows the four values.

The plan has to include the assistant. In the Control Plane's catalogue, the
three entitlements are:

```text
ai.assistant   boolean
ai.tools       boolean
ai.requests    quota, per month; the limit is model calls
```

A product with no Control Plane configured runs ungated on its own
catalogue, which is how it runs locally.

## Where a product's AI lives

```text
services/api/koras_api/ai/
  agents.py      AGENTS: the agents this product offers
  tools.py       TOOLS: what they may propose
  prompts.py     PROMPTS: their instructions, versioned
  knowledge.py   SOURCES: what retrieval may see (none by default)
  models.py      CATALOGUE: which gateway model answers each alias
```

The registries are built once at import by `services/api/koras_api/ai/__init__.py`.
An agent naming a tool or a prompt nobody registered fails at startup, which
is the only good time for it to fail.

## Creating a tool

A tool is typed, permissioned, classed, and given its context by the runtime.
It reads its tenant from the context and never from the model.

```python
from typing import Any

from koras_ai import Operation, ToolContext, define_tool
from pydantic import BaseModel, Field
from sqlalchemy import text


class RenameInput(BaseModel):
    file_id: str = Field(description="The file to rename")
    name: str = Field(min_length=1, max_length=255)


async def rename_file(ctx: ToolContext, args: RenameInput) -> dict[str, Any]:
    assert ctx.session is not None
    await ctx.session.execute(
        text(
            "update public.files set name = :name "
            "where tenant_id = :tenant_id and id::text = :file_id"
        ),
        {"name": args.name, "tenant_id": ctx.context.tenant_id, "file_id": args.file_id},
    )
    await ctx.session.commit()
    return {"renamed": args.file_id, "to": args.name}


TOOLS = (
    define_tool(
        id="files.rename",
        description="Rename one of this organization's files.",
        permission="files.manage",
        operation=Operation.WRITE,
        input_model=RenameInput,
        execute=rename_file,
    ),
)
```

What the operation class decides:

| Class | Executes | Approval | Who may approve |
|-------|----------|----------|-----------------|
| read | at once, when the caller holds the permission | none, unless the tool asks | — |
| write | after approval | required | holds `ai.approve` and the tool's permission |
| destructive | after approval | required | the above, and an owner or administrator |
| external | after approval | required | holds `ai.approve` and the tool's permission |

`permission` is a name from the product's catalogue in
`packages/permissions/src/index.ts`, mirrored in
`python-packages/koras-auth/src/koras_auth/permissions.py`. Add a new
permission to both, in the same commit; the starter's test says which side
is behind. A tool needing a service the runtime does not open, an object
store say, gets it through `ToolContext.services`, which the API's dependency
fills.

## Creating an agent

```python
from koras_ai import ModelAlias, define_agent

AGENTS = (
    define_agent(
        id="assistant",
        name="Assistant",
        model=ModelAlias.BALANCED,
        prompt_id="assistant.system",
        capabilities=("chat", "tools"),
        tools=("files.list", "files.rename"),
        max_turns=4,
    ),
)
```

The first agent listed is what a conversation runs as when none is named.
`model` is an alias and nothing else; an agent naming a vendor model fails
at definition. The tool list is what the agent may propose, and the caller's
permissions narrow it further at every turn.

## Creating a prompt

```python
from koras_ai import define_prompt

PROMPTS = (
    define_prompt(
        id="assistant.system",
        version=2,
        variables=("product", "page"),
        template="You are the assistant inside {product}. The person is looking at {page}.",
    ),
)
```

Variables are declared and checked both ways at definition and at render.
The runtime supplies `product` and `page` to an agent's prompt; anything
else a product renders itself with `PromptRegistry.render` before it reaches
a model. Add a version to change a prompt, keep the old one until nothing
names it, and the registry answers the highest.

## Invoking AI outside a conversation

A product feature that wants one model call, a summary say, builds a request
under an alias and asks the runtime, which meters it like a turn:

```python
from koras_ai import GenerateRequest, Message

result = await ai.runtime.generate(
    ai.context,
    GenerateRequest(
        model="koras-fast",
        messages=(Message("system", "Summarise in two sentences."), Message("user", text)),
    ),
    agent_id="summariser",
)
```

`ai` is the `AiDep` from `services/api/koras_api/core/ai.py`, so the
tenant, the plan and the routing are already decided. There is no way to
call the gateway from a route without it.

## Adding page context

A page that wants the assistant to know what it shows declares it:

```tsx
import { AIPageScope } from '../assistant/context'

export default async function DocumentPage({ params }: { params: { id: string } }) {
  return (
    <>
      <AIPageScope type="document" id={params.id} />
      {/* the page */}
    </>
  )
}
```

The launcher sends the pair when it starts a conversation; the prompt mentions
it; the conversation row records it. It scopes nothing: a tool that reads the
resource still runs under the tenant session and its own permission.

## Registering knowledge

```python
from koras_ai import define_knowledge_source

SOURCES = (
    define_knowledge_source(
        id="documents",
        resource_type="document",
        description="The documents this organization uploaded",
    ),
)
```

A source is a declaration. Retrieval needs a `KnowledgeIndex` behind it,
which the starter does not ship; `python-packages/koras-ai/src/koras_ai/knowledge.py`
has the protocols, a chunker and an embedder. A product that builds one
writes the index, an ingestion pipeline that fills it under a
`RetrievalScope`, and a tool or an agent step that asks it and renders the
citations with `AICitations`.

## Requiring approval on a read

```python
define_tool(..., operation=Operation.READ, approval=True)
```

A read that touches something sensitive can wait for a person. Nothing can
make a write not wait.

## Testing a product's AI

- A tool's executor is a function of a `ToolContext`; test it with a context
  built by hand and a session or a fake service.
- A turn is `AIRuntime.send` with a `FakeProvider` scripted to propose the
  tool, and an `InMemoryStore`; the package's own tests under
  `python-packages/koras-ai/tests/` are the pattern.
- The routes are tested with the dependency overridden, as
  `tests/unit/test_ai_api.py` does.
- The page is exercised by `e2e/assistant.spec.ts` against a build with no
  API, which is the state the browser test can reach.

## Turning it off

A product generated without `ai` has none of this. A customer whose plan
lacks the assistant sees the module locked and every route refuses with
402. A caller without `ai.use` sees nothing and gets 403.
