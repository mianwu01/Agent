# Text-only partner probe

State: s003; native sampled-reply success rate: 0.500.

| Arm | Candidate | Success rate | Delta |
|---|---|---:|---:|
| VS batch | My mobile number is 555-123-2002. | 1.000 | +0.500 |
| VS batch | You can verify me using 555-123-2002. I’m currently in France and need help getting my mobile data working properly. | 1.000 | +0.500 |
| VS batch | Sure, my phone number is 555-123-2002. Once verified, could you help me get excellent internet speed? I don’t have Wi‑Fi available. | 0.500 | +0.000 |
| Outcome feedback | You can verify me using my mobile number: 555-123-2002. | 1.000 | +0.500 |
| Outcome feedback | My phone number is 555-123-2002. I’m currently in France, if that helps with the verification. | 0.500 | +0.000 |
| Outcome feedback | I don’t have a customer ID, but my mobile number is 555-123-2002. Will that be sufficient to verify the account? | 1.000 | +0.500 |

Provider usage: {'prompt_tokens': 1432087, 'completion_tokens': 20010}.

Each candidate has two continuations and a model fidelity assessment. The VS arm uses one candidate batch, not iterative VS-Multi. These are exploratory effects; the native-reply baseline at this state consists of identical phone-number replies.
