# Metrics Label Cardinality Policy

Deployment manifests can declare metrics under `metrics` or
`observability.metrics`. Before rollout, `ao deploy` validates every declared
label against the bounded cardinality policy.

Unbounded labels such as task IDs, worker IDs, request paths, emails, user IDs,
or raw error messages can create high-cardinality time series. A rollout is
blocked unless the manifest includes an owner-approved exception.

## Allowed Labels

The default deployment policy allows these bounded labels:

| Label | Allowed values |
| --- | --- |
| `deployment.stage` | `dev`, `staging`, `prod` |
| `deployment.result` | `success`, `failure`, `rolled_back` |
| `task.priority` | `low`, `normal`, `high`, `critical` |
| `task.queue` | `default`, `batch`, `realtime` |
| `task.status` | `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `worker.pool` | `default`, `cpu`, `gpu`, `io` |
| `worker.region` | `local`, `us-east`, `us-west`, `eu`, `apac` |
| `worker.state` | `idle`, `busy`, `draining`, `offline` |

Custom labels are allowed when the manifest declares a finite value list with no
more than 50 values.

## Example

```yaml
metrics:
  - name: task.events
    labels:
      task.status:
        - queued
        - running
        - succeeded
        - failed
      worker.pool:
        - cpu
        - gpu
```

## Exceptions

Use an exception only for short-lived debugging or migration rollouts. It must
name the metric, label, approver, and reason.

```yaml
metrics:
  - name: task.events
    labels:
      task.id:
        cardinality: unbounded

metrics_label_exceptions:
  - metric: task.events
    label: task.id
    approved_by: observability-owner
    reason: short-lived incident debugging rollout
```
