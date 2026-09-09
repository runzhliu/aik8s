"""Version-adapted AIBrix observability views; upstream scope, live metric contracts."""
import json
from pathlib import Path
R=Path(__file__).resolve().parent;DS={'type':'prometheus','uid':'aibrix-perf-prometheus'}
M='model_name="$model"';V='job="aibrix-vllm",replica!="",'+M
G='job="aibrix-gateway-plugins",model="$model"'
LINKS=[('Overview','aibrix-perf-overview'),('Control plane','deksjt08bf4lce'),('Envoy','beidja4ourr40f'),('Routing & cache','5rRLZ0zDz'),('vLLM engine','ce2azhsbhel8gd'),('GPU & capacity','aibrix-perf-gpu')]

def dashboard(uid,title,note,specs):
    panels=[{'id':1,'type':'text','title':'Scope & metric contract','gridPos':{'x':0,'y':0,'w':24,'h':3},'options':{'mode':'markdown','content':note}}]
    for i,s in enumerate(specs):
        title,expr,unit,*rest=s;legend=rest[0] if rest else '{{replica}}';ptype=rest[1] if len(rest)>1 else 'timeseries'
        targets=[{'refId':chr(65+j),'expr':e,'legendFormat':(('P50 · ' if j==0 else 'P95 · ') if 'P50 / P95' in title else ('running · ' if j==0 else 'waiting · ') if title=='Running / waiting' else '')+legend,'datasource':DS} for j,e in enumerate(expr if isinstance(expr,list) else [expr])]
        panel={'id':i+2,'type':ptype,'title':title,'datasource':DS,'gridPos':{'x':(i%2)*12,'y':3+(i//2)*8,'w':12,'h':8},'targets':targets,'fieldConfig':{'defaults':{'unit':unit,'color':{'mode':'palette-classic'},'custom':{'drawStyle':'line','lineWidth':2,'fillOpacity':10,'spanNulls':False}},'overrides':[]},'options':{'legend':{'displayMode':'table','placement':'bottom','calcs':['lastNotNull','max']},'tooltip':{'mode':'multi','sort':'desc'}}}
        if ptype=='stat':panel['options']={'reduceOptions':{'calcs':['lastNotNull'],'fields':'','values':False},'colorMode':'value','graphMode':'area','textMode':'auto'}
        panels.append(panel)
    return {'uid':uid,'title':TITLES[uid],'schemaVersion':39,'version':2,'editable':True,'tags':['AIBrix','DS V4 Flash','validated metric contract'],'timezone':'browser','refresh':'15s','time':{'from':'now-30m','to':'now'},'annotations':{'list':[{'builtIn':1,'datasource':{'type':'grafana','uid':'-- Grafana --'},'enable':True,'hide':True,'iconColor':'rgba(0,211,255,1)','name':'Annotations & Alerts','type':'dashboard'}]},'templating':{'list':[{'name':'model','label':'Model','type':'constant','query':'dsv4-flash-aibrix-perf','current':{'text':'dsv4-flash-aibrix-perf','value':'dsv4-flash-aibrix-perf'},'hide':0}]},'links':[{'title':t,'type':'link','url':'/d/'+u,'includeVars':True,'keepTime':True} for t,u in LINKS],'panels':panels}

TITLES={u:'AIBrix · '+t for t,u in LINKS}
def h(metric,q=.95,selector=V,group='replica'):
    return f'histogram_quantile({q}, sum by (le{", "+group if group else ""}) (rate({metric}_bucket{{{selector}}}[$__rate_interval])))'

def build():
    views={}
    def add(uid,note,specs):views[uid+'.json']=json.dumps(dashboard(uid,TITLES[uid],note,specs),ensure_ascii=False)
    add('aibrix-perf-overview','**2 replicas × TP8 · vLLM · AIBrix v0.7.0.** Client TTFT starts before POST and ends at first nonempty content/reasoning. Client TPOT = (last − first content time)/(output tokens − 1). Histogram quantiles are estimates; exact phase results remain in JSONL. Scrape UP is availability of metrics, not Kubernetes readiness. Shared Envoy and control-plane metrics include other tenants.',[
        ('Engine scrape targets UP',f'sum(up{{job="aibrix-vllm"}})','short','UP','stat'),
        ('Client completed requests by phase','sum by (phase,result) (aik8s_benchmark_requests_total{phase!~"warmup.*|smoke",result="ok"})','short','{{phase}} · {{result}}'),
        ('Client TTFT P50 / P95', [h('aik8s_benchmark_ttft_seconds',q,'phase!~"warmup.*|smoke"','phase') for q in [.5,.95]],'s','{{phase}}'),
        ('Client TPOT P50 / P95',[h('aik8s_benchmark_tpot_seconds',q,'phase!~"warmup.*|smoke"','phase') for q in [.5,.95]],'s','{{phase}}'),
        ('Client output throughput · completed phases','aik8s_benchmark_phase_output_tokens_per_second','suffix:tok/s','{{phase}}'),
        ('Engine output throughput',f'sum by (replica) (rate(vllm:generation_tokens_total{{{V}}}[$__rate_interval]))','suffix:tok/s'),
        ('Engine TTFT P95 · aggregated replicas',h('vllm:time_to_first_token_seconds',group=''),'s','Engine TTFT P95'),
        ('Running / waiting', [f'sum by (replica) (vllm:num_requests_{x}{{{V}}})' for x in ['running','waiting']],'short','{{replica}}'),
        ('Collection health by job','min by(job) (up)','short','{{job}}'),
        ('Completed phase request rate','aik8s_benchmark_phase_request_rate','reqps','{{phase}}'),
        ('Active experiment alerts','ALERTS{scope="aibrix-performance-lab",alertstate="firing"}','short','{{alertname}}'),
        ('Recovery probe completed requests','sum by(result)(aik8s_benchmark_requests_total{phase="eviction-c4"})','short','{{result}}')])
    add('deksjt08bf4lce','**Shared AIBrix controller.** These are cluster-wide reconcile/workqueue statistics, not isolated model request metrics. A healthy reconcile loop does not prove model readiness. Autoscaling, P/D separation and external distributed KV cache are not enabled in this experiment.',[
        ('Controller scrape UP','up{job="aibrix-controller"}','short','Controller','stat'),
        ('Reconcile rate by result','sum by(controller,result)(rate(controller_runtime_reconcile_total{job="aibrix-controller"}[$__rate_interval]))','ops','{{controller}} · {{result}}'),
        ('Reconcile errors','sum by(controller)(rate(controller_runtime_reconcile_errors_total{job="aibrix-controller"}[$__rate_interval]))','ops','{{controller}}'),
        ('Reconcile P95',h('controller_runtime_reconcile_time_seconds',selector='job="aibrix-controller"',group='controller'),'s','{{controller}}'),
        ('Workqueue depth','workqueue_depth{job="aibrix-controller"}','short','{{name}}'),
        ('Workqueue retries','rate(workqueue_retries_total{job="aibrix-controller"}[$__rate_interval])','ops','{{name}}'),
        ('Active reconcile workers','controller_runtime_active_workers{job="aibrix-controller"}','short','{{controller}}'),
        ('Controller CPU cores','rate(process_cpu_seconds_total{job="aibrix-controller"}[$__rate_interval])','cores','Controller'),
        ('Controller RSS','process_resident_memory_bytes{job="aibrix-controller"}','bytes','Controller'),
        ('Queue wait P95',h('workqueue_queue_duration_seconds',selector='job="aibrix-controller"',group='name'),'s','{{name}}')])
    E='job="aibrix-envoy",envoy_http_conn_manager_prefix="http-10080"'
    add('beidja4ourr40f','**Shared Envoy data plane · all tenants on port 10080.** HTTP connections are gauges. HTTP request latency includes full streaming response time and is not TTFT. Model-specific latency is available in the client and engine views.',[
        ('Envoy scrape UP','up{job="aibrix-envoy"}','short','Envoy','stat'),
        ('HTTP responses by class',f'sum by(envoy_response_code_class)(rate(envoy_http_downstream_rq_xx{{{E}}}[$__rate_interval]))','reqps','HTTP {{envoy_response_code_class}}xx'),
        ('Active HTTP connections',f'envoy_http_downstream_cx_active{{{E}}}','short','Connections'),
        ('Active HTTP requests',f'envoy_http_downstream_rq_active{{{E}}}','short','Requests'),
        ('Upstream connections by cluster','envoy_cluster_upstream_cx_active{job="aibrix-envoy"}','short','{{envoy_cluster_name}}'),
        ('Upstream connection failures','rate(envoy_cluster_upstream_cx_connect_fail{job="aibrix-envoy"}[$__rate_interval])','ops','{{envoy_cluster_name}}'),
        ('Envoy allocated memory','envoy_server_memory_allocated{job="aibrix-envoy"}','bytes','Allocated'),
        ('Envoy heap size','envoy_server_memory_heap_size{job="aibrix-envoy"}','bytes','Heap')])
    add('5rRLZ0zDz','**Routing and cache · model filtered.** Request success counts use only `status="gateway_request_success"`; other stages are not added. Error stages are diagnostic events, not deduplicated failed requests. Cache hit ratio is token-weighted from engine counters; indexer status is not a hit rate. P/D and distributed cache panels are excluded because these capabilities are not enabled.',[
        ('Gateway success events',f'sum(rate(gateway_request_model_success_total{{{G},status="gateway_request_success"}}[$__rate_interval]))','ops','Successful request events'),
        ('Gateway failures by stage',f'sum by(status,status_code)(rate(gateway_request_model_fail_total{{{G}}}[$__rate_interval]))','ops','{{status}} · {{status_code}}'),
        ('Replica completed requests',f'sum by(replica)(rate(vllm:request_success_total{{{V}}}[$__rate_interval]))','reqps'),
        ('Prefix cache token hit ratio',f'sum by(replica)(rate(vllm:prefix_cache_hits_total{{{V}}}[$__rate_interval])) / sum by(replica)(rate(vllm:prefix_cache_queries_total{{{V}}}[$__rate_interval]))','percentunit'),
        ('Prefix cache queried tokens',f'sum by(replica)(rate(vllm:prefix_cache_queries_total{{{V}}}[$__rate_interval]))','suffix:tok/s'),
        ('KV cache utilization',f'max by(replica)(vllm:kv_cache_usage_perc{{{V}}})','percentunit'),
        ('Prefix indexer status · shared','aibrix_prefix_cache_indexer_status{job="aibrix-gateway-plugins"}','short','Indexer'),
        ('Gateway plugin RSS','process_resident_memory_bytes{job="aibrix-gateway-plugins"}','bytes','Plugin')])
    add('ce2azhsbhel8gd','**vLLM v0.26 metrics contract.** TTFT, request-average TPOT and inter-token latency have distinct histograms. Never average pod quantiles: merge histogram buckets before histogram_quantile. Prefix cache uses counters; this engine has no v0-style CPU swap/cache panels.',[
        ('Engine TTFT P95',h('vllm:time_to_first_token_seconds'),'s'),
        ('Request-average TPOT P95',h('vllm:request_time_per_output_token_seconds'),'s'),
        ('Inter-token latency P95',h('vllm:inter_token_latency_seconds'),'s'),
        ('End-to-end latency P95',h('vllm:e2e_request_latency_seconds'),'s'),
        ('Queue time P95',h('vllm:request_queue_time_seconds'),'s'),
        ('Prefill time P95',h('vllm:request_prefill_time_seconds'),'s'),
        ('Running requests',f'max by(replica)(vllm:num_requests_running{{{V}}})','short'),
        ('Waiting requests',f'max by(replica)(vllm:num_requests_waiting{{{V}}})','short'),
        ('Generated token throughput',f'sum by(replica)(rate(vllm:generation_tokens_total{{{V}}}[$__rate_interval]))','suffix:tok/s'),
        ('Prompt token throughput',f'sum by(replica)(rate(vllm:prompt_tokens_total{{{V}}}[$__rate_interval]))','suffix:tok/s'),
        ('KV cache utilization',f'max by(replica)(vllm:kv_cache_usage_perc{{{V}}})','percentunit'),
        ('Preemption rate',f'sum by(replica)(rate(vllm:num_preemptions_total{{{V}}}[$__rate_interval]))','ops')])
    add('aibrix-perf-gpu','**Two selected H20-3e nodes · 16 GPUs.** DCGM exporter runs on the host. GPU utilization is not tensor-core utilization. Memory here is frame-buffer MiB, independent of engine KV cache fraction. These are capacity observations, not proof of an optimal NUMA/NVLink placement.',[
        ('GPU utilization','max by(node_alias,gpu)(DCGM_FI_DEV_GPU_UTIL{job="dcgm",node_alias!=""})','percent','{{node_alias}} · GPU{{gpu}}'),
        ('Frame-buffer used','max by(node_alias,gpu)(DCGM_FI_DEV_FB_USED{job="dcgm",node_alias!=""}) * 1048576','bytes','{{node_alias}} · GPU{{gpu}}'),
        ('Tensor pipeline active','max by(node_alias,gpu)(DCGM_FI_PROF_PIPE_TENSOR_ACTIVE{job="dcgm",node_alias!=""})','percentunit','{{node_alias}} · GPU{{gpu}}'),
        ('DRAM active','max by(node_alias,gpu)(DCGM_FI_PROF_DRAM_ACTIVE{job="dcgm",node_alias!=""})','percentunit','{{node_alias}} · GPU{{gpu}}'),
        ('Power usage','max by(node_alias,gpu)(DCGM_FI_DEV_POWER_USAGE{job="dcgm",node_alias!=""})','watt','{{node_alias}} · GPU{{gpu}}'),
        ('GPU temperature','max by(node_alias,gpu)(DCGM_FI_DEV_GPU_TEMP{job="dcgm",node_alias!=""})','celsius','{{node_alias}} · GPU{{gpu}}'),
        ('GPU clocks','max by(node_alias,gpu)(DCGM_FI_DEV_SM_CLOCK{job="dcgm",node_alias!=""})','suffix:MHz','{{node_alias}} · GPU{{gpu}}'),
        ('Model container CPU cores','sum by(replica)(rate(container_cpu_usage_seconds_total{job="kubelet-cadvisor",replica!="",namespace="inference-lab",pod=~"dsv4-flash-aibrix-perf-.*",container="vllm"}[$__rate_interval]))','cores'),
        ('Model container working set','sum by(replica)(container_memory_working_set_bytes{job="kubelet-cadvisor",replica!="",namespace="inference-lab",pod=~"dsv4-flash-aibrix-perf-.*",container="vllm"})','bytes'),
        ('DCGM scrape UP','up{job="dcgm",node_alias!=""}','short','{{node_alias}}')])
    return views

if __name__=='__main__':
    out=R/'dashboards';out.mkdir(exist_ok=True)
    for name,data in build().items():(out/name).write_text(data)
    print('Generated six dashboards')
