# APF Isolation Case Illustrations and Evidence

| Asset | Purpose | Source and Production Method |
| --- | --- | --- |
| grafana-case.png | Shows the relationships among seats, execution, rejection, queuing, and waiting | Actual Grafana dedicated dashboard screenshot; fixed real experiment time range, address bar not shown |
| grafana-case-mobile.png | Viewing six monitoring panels on mobile | Same real dashboard, screenshot after automatic reflow to a single column at 430 px width |
| client-outcomes.png | Compares request outcomes between batch accounts and control accounts | results.json; deterministic plotting |
| client-outcomes-mobile.png | Mobile version of the results chart | Same data, independently reflowed |
| results.json / requests.csv / metrics.json | Supports verification of charts and values | Experiment client logs and Prometheus API; internal network addresses, cluster names, and credentials removed |

Technical figures follow the project's light color scheme and Chinese font. Screenshots retain the real graphics and coordinates; synthetic images are not passed off as Grafana. Screenshots may only crop irrelevant whitespace; metric curves must not be modified.
