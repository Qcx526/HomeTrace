"""Environment boundary: this stage implements simulated navigation only."""

from typing import Protocol

from hometrace.models import NavigationResult, Observation, Viewpoint


class EnvironmentAdapter(Protocol):
    def list_viewpoints(self) -> list[Viewpoint]: ...

    def navigate_to(self, viewpoint_id: str) -> NavigationResult: ...

    def observe(self, viewpoint_id: str) -> Observation | None: ...


class MockAdapter:
    """Expose synthetic fixture observations after a simulated arrival."""

    def __init__(
        self,
        viewpoints: list[Viewpoint],
        observations: dict[str, Observation],
        unreachable_viewpoints: set[str] | None = None,
    ) -> None:
        self._viewpoints = list(viewpoints)
        known = {point.viewpoint_id for point in viewpoints}
        if len(known) != len(viewpoints):
            raise ValueError("MockAdapter requires unique viewpoint IDs")
        for viewpoint_id, observation in observations.items():
            if viewpoint_id not in known or observation.viewpoint_id != viewpoint_id:
                raise ValueError("MockAdapter observation must match a known viewpoint")
            if (
                observation.data_source != "fixture"
                or observation.image_path is not None
                or observation.image_hash is not None
            ):
                raise ValueError("MockAdapter accepts synthetic fixtures without images only")
        self._observations = dict(observations)
        self._unreachable = set(unreachable_viewpoints or set())
        if not self._unreachable <= known:
            raise ValueError("MockAdapter unreachable viewpoints must be known")
        self._known = known
        self._arrived_at: str | None = None

    def list_viewpoints(self) -> list[Viewpoint]:
        return list(self._viewpoints)

    def navigate_to(self, viewpoint_id: str) -> NavigationResult:
        self._arrived_at = None
        if viewpoint_id not in self._known or viewpoint_id in self._unreachable:
            return NavigationResult(viewpoint_id, "UNREACHABLE")
        self._arrived_at = viewpoint_id
        return NavigationResult(viewpoint_id, "ARRIVED")

    def observe(self, viewpoint_id: str) -> Observation | None:
        if self._arrived_at != viewpoint_id:
            return None
        return self._observations.get(viewpoint_id)
