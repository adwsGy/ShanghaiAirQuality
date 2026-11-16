"""Application contracts shared by graph nodes, HTTP handlers and the workbench."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from api.workspace import AnalysisContext


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class AnalysisView(Contract):
    task: Literal['trend', 'compare', 'season', 'stations', 'distribution', 'episodes'] = 'trend'
    context: AnalysisContext = Field(default_factory=AnalysisContext)
    month: str | None = None
    detailObject: str | None = None
    detailDay: str | None = None
    detailTab: Literal['daily','hourly','source'] = 'daily'


class SessionRequest(Contract):
    dataset_version: str
    view: AnalysisView = Field(default_factory=AnalysisView)


class ActionRequest(Contract):
    client_request_id: str = Field(min_length=8, max_length=80)
    expected_revision: int = Field(ge=0)
    action: Literal['apply', 'undo'] = 'apply'
    view: AnalysisView | None = None

    @model_validator(mode='after')
    def require_view(self):
        if self.action == 'apply' and self.view is None:
            raise ValueError('更新条件需要提供完整视图。')
        return self


class RunRequest(Contract):
    client_request_id: str = Field(min_length=8, max_length=80)
    expected_revision: int = Field(ge=0)
    question: str = Field(min_length=1, max_length=1200)
    web_search_enabled: bool = True


class AnalysisPlan(Contract):
    tool: Literal['compare_periods', 'compare_distributions', 'query_trend', 'seasonal_matrix', 'station_analysis', 'find_episodes', 'inspect_month', 'search_web', 'request_clarification']
    tool_call_id: str = Field(min_length=1, max_length=160)
    arguments: dict[str, Any]
    update_view: bool = False


class Summary(Contract):
    mean: float | None
    p90: float | None
    n: int = Field(ge=0)
    expected: int = Field(ge=0)
    unit: Literal['μg/m³']


class ComparisonMonth(Contract):
    month: int = Field(ge=1, le=12)
    base: Summary
    target: Summary
    delta: float | None
    base_period: str | None = None
    target_period: str | None = None


class ComparisonData(Contract):
    rows: list[ComparisonMonth]
    base: Summary
    target: Summary
    delta: float | None


class Provenance(Contract):
    rule_version: str
    method: str
    source_level: Literal['city_archive', 'site_archive']
    query_version: int = 1


class Point(Summary):
    period: str
    start: str | None = None
    end: str | None = None


class Cell(Summary):
    year: int
    month: int
    period: str


class TrendData(Contract):
    points: list[Point]


class SeasonData(Contract):
    cells: list[Cell]
    month_order: list[int]


class DistributionCurve(Contract):
    label: str
    n: int
    points: list[list[float]]


class DistributionData(ComparisonData):
    curves: list[DistributionCurve]


class StationRow(Contract):
    station_id: str
    name: str
    base: Summary | None
    target: Summary
    delta: float | None
    coordinate: dict | None


class StationData(Contract):
    rows: list[StationRow]


class StationSeries(Contract):
    station_id: str
    name: str
    points: list[Point]


class StationTrendData(Contract):
    series: list[StationSeries]


class Episode(Contract):
    start: str
    end: str
    days: int
    mean: float
    maximum: float


class DailyValue(Contract):
    date: str
    value: float | None


class EpisodesData(Contract):
    episodes: list[Episode]
    threshold: float
    minimum_days: int
    daily: list[DailyValue]


class ObservationData(TrendData):
    observations: dict


class ToolResult(Contract):
    dataset_version: str
    result_id: str
    task: Literal['trend', 'compare', 'season', 'stations', 'distribution', 'episodes', 'station_trends', 'observations']
    context: AnalysisContext
    object_name: str
    unit: Literal['μg/m³']
    summary: Summary | None
    data: TrendData | SeasonData | DistributionData | ComparisonData | StationData | StationTrendData | EpisodesData | ObservationData
    provenance: Provenance

    @model_validator(mode='after')
    def matching_data(self):
        expected = {'trend': TrendData, 'compare': ComparisonData, 'season': SeasonData,
                    'stations': StationData, 'distribution': DistributionData, 'episodes': EpisodesData,
                    'station_trends': StationTrendData, 'observations': ObservationData}[self.task]
        if type(self.data) is not expected:
            raise ValueError('结果数据与任务类型不一致')
        return self


class ViewSpec(Contract):
    task: Literal['trend', 'compare', 'season', 'stations', 'distribution', 'episodes']
    data_ref: str
    title: str
    selected_month: str | None = None
    secondary_refs: list[str] = Field(default_factory=list)


class Fact(Contract):
    id: str
    text: str
    result_id: str
    month: int | None = None
    date: str | None = None
    station_id: str | None = None
    selection_kind: Literal['none','month','day'] = 'none'


class WebSource(Contract):
    title: str
    url: str
    snippet: str
    date: str | None = None


class Answer(Contract):
    text: str
    fact_ids: list[str]
    source: Literal['computed_facts','computed_fallback','external_sources','model_analysis','model_explanation'] = 'computed_facts'
    sources: list[WebSource] = Field(default_factory=list)


class ResultEnvelope(Contract):
    session_id: str
    run_id: str
    dataset_version: str
    state_revision: int
    context: AnalysisContext
    result_refs: list[str]
    view_spec: ViewSpec
    facts: list[Fact]
    answer: Answer


class AnalysisEvent(Contract):
    event_id: int
    run_id: str
    event: Literal['run_started', 'progress', 'tool_completed', 'clarification_required', 'result', 'error', 'cancelled']
    state_revision: int
    data: dict[str, Any]


class ClarificationRequest(Contract):
    client_request_id: str = Field(min_length=8, max_length=80)
    expected_revision: int = Field(ge=0)
    choice: Literal['calendar_winter', 'cross_year_winter']


class CancelRequest(Contract):
    client_request_id: str = Field(min_length=8,max_length=80)


class RecoveryRequest(Contract):
    client_request_id: str = Field(min_length=8,max_length=80)
    expected_revision: int = Field(ge=0)
