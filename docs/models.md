# Model discovery and compatibility

Settings discovers models through the backend using the configured OpenAI API
key. The key never appears in model responses, logs, SQLite settings or backups.
The frontend receives identifiers and capability descriptions only. Missing keys
show documented defaults with availability marked unknown; network, permission,
authentication and rate-limit errors have actionable messages.

The [OpenAI models API](https://developers.openai.com/api/reference/resources/models/methods/list)
provides identifiers, creation/ownership and optional shutdown information. It does
not provide the complete capability or pricing information needed by this app.
Account visibility also does not guarantee that a particular endpoint request,
project permission, quota or billing configuration will succeed.

## How selections work

All six processing stages retain independent model choices. The existing default
is GPT-6 Astra; semantic retrieval defaults to Text Embedding 3 Small. Selecting a
default for all stages is a convenience; saved stage overrides are preserved.
Settings may be saved offline. Checking the model setup makes metadata requests,
without sending course material or creating a generation response.

The small exact-ID catalogue in
`src/anki_generator/llm/model_catalogue.py` was checked on **9 November 2026**:

| Model | Documented capability used here | Official reference |
| --- | --- | --- |
| GPT-6 Astra | Responses, structured output, image input; low/medium/high/xhigh/max reasoning | [Model page](https://developers.openai.com/api/docs/models/gpt-6-astra) |
| GPT-6.1 Sol | Responses, structured output, image input; low/medium/high/xhigh/max reasoning | [Model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol) |
| GPT-6 Luna | Responses, structured output, image input; none/low/medium/high/xhigh/max reasoning | [Model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| GPT-4.1 | Responses, structured output and image input; adjustable reasoning parameter omitted | [Model page](https://developers.openai.com/api/docs/models/gpt-4.1) |
| Text Embedding 3 Small | Neural text embeddings; incompatible with card-processing stages | [Model page](https://developers.openai.com/api/docs/models/text-embedding-3-small) |
| Text Embedding 3 Large | Neural text embeddings; incompatible with card-processing stages | [Model page](https://developers.openai.com/api/docs/models/text-embedding-3-large) |

Processing stages can attach source evidence images as well as text, so compatible
general models need Responses, structured output and image input. Embedding choices
remain separate. The global adjustable-reasoning control retains the existing
low/medium/high/xhigh/max choices. Models without adjustable reasoning omit that
parameter. No capability is inferred from a model-name prefix, snapshot suffix,
fine-tuning parent or the account model listing. No prices are inferred or added by
discovery; the separate existing usage estimate remains explicitly dated and
limited to its verified pricing schedule.

Account models absent from the catalogue are labelled **unverified**. Advanced
users may enter custom identifiers. A custom ID absent from the account list is
checked with the model metadata retrieval API. A visible custom model remains a
warning because its Responses, structured-output and image compatibility are
unknown. The provider can still reject it. The explicit connection test performs a
small actual structured-output request and may incur API usage; it is distinct
from metadata validation and does not prove vision or academic quality.

The semantic-search selector also supports custom embedding identifiers. These
persist with the selected vector dimensions and receive the same account-access
check. Unknown embedding models remain unverified: they must support the
Embeddings endpoint and the requested dimensions, and the provider may reject
either. Returned vectors must match the requested dimensions, contain finite
values and be nonzero. The existing 64–3072 application dimension bounds and
1536-dimension maximum for Text Embedding 3 Small remain enforced. Choosing a
custom identifier never implies known embedding capability or pricing.

## Cache and generation safeguards

Successful account listings are cached in process memory for ten minutes. Cache
identity includes the credential and configured API origin; neither the credential
nor its cache identity is returned. Changing/removing a key invalidates discovery,
and **Refresh models** always bypasses the cache. A failed refresh discards old
availability instead of representing stale results as current. Restarting clears
the cache. Saved model choices are never silently replaced after refresh.

Generation validates the effective models and embedding choice before creating a
durable job, outside SQLite's write transaction. Known incompatible models,
inaccessible models, missing credentials and discovery errors block submission
with a corrective message. Interpretation-only tasks validate their interpretation
model; local extraction remains offline and requires no key or model listing.
Resume/retry checks the frozen run configuration rather than substituting current
settings. Normal provider errors and all checkpoint/recovery contracts still
apply after preflight; metadata cannot guarantee future request success.

The only discovery bypass is an explicitly injected Python test provider. There
is no HTTP or environment flag that substitutes synthetic generation responses.
Tests exercise the official SDK with mocked metadata, sanitized failures and an
isolated loopback transport. No live account or paid generation result is claimed
by those tests.

## Maintenance

When adding a recognized model, fetch its exact official model page, verify each
declared capability and reasoning value, update the catalogue date and this table,
and add request-shape and validation tests. Keep unknown models explicitly unknown
until this evidence exists. Do not make a model migration or change saved/default
selections merely to expand discovery.
