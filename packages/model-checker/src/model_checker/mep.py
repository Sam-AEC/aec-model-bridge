"""MEP (Mechanical, Electrical, Plumbing) systems validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MEPConnectivityIssue:
    """Issue found during MEP connectivity validation."""

    element_id: str | int
    element_type: str
    issue_type: str
    description: str
    system_name: str | None = None
    location: dict[str, float] | None = None


class MEPConnectivityValidator:
    """Validator for MEP system connectivity."""

    def __init__(self) -> None:
        """Initialize MEP connectivity validator."""
        self.issues: list[MEPConnectivityIssue] = []

    def validate_duct_connections(
        self, ducts: list[dict[str, Any]], systems: list[dict[str, Any]]
    ) -> list[MEPConnectivityIssue]:
        """Validate duct connections and system membership.

        Args:
            ducts: List of duct dictionaries with 'id', 'start_connector', 'end_connector', 'system_id'
            systems: List of MEP system dictionaries with 'id', 'name', 'type'

        Returns:
            List of connectivity issues
        """
        issues = []
        system_map = {sys["id"]: sys for sys in systems}

        for duct in ducts:
            # Check if duct belongs to a system
            if not duct.get("system_id"):
                issue = MEPConnectivityIssue(
                    element_id=duct["id"],
                    element_type="duct",
                    issue_type="no_system",
                    description="Duct is not part of any MEP system",
                )
                issues.append(issue)
                self.issues.append(issue)
                continue

            # Check if system exists
            if duct["system_id"] not in system_map:
                issue = MEPConnectivityIssue(
                    element_id=duct["id"],
                    element_type="duct",
                    issue_type="invalid_system",
                    description=f"Duct references invalid system ID: {duct['system_id']}",
                )
                issues.append(issue)
                self.issues.append(issue)
                continue

            # Check connectors
            if not duct.get("start_connector") or not duct["start_connector"].get("connected"):
                issue = MEPConnectivityIssue(
                    element_id=duct["id"],
                    element_type="duct",
                    issue_type="disconnected_start",
                    description="Duct start connector is not connected",
                    system_name=system_map[duct["system_id"]]["name"],
                )
                issues.append(issue)
                self.issues.append(issue)

            if not duct.get("end_connector") or not duct["end_connector"].get("connected"):
                issue = MEPConnectivityIssue(
                    element_id=duct["id"],
                    element_type="duct",
                    issue_type="disconnected_end",
                    description="Duct end connector is not connected",
                    system_name=system_map[duct["system_id"]]["name"],
                )
                issues.append(issue)
                self.issues.append(issue)

        return issues

    def validate_pipe_connections(
        self, pipes: list[dict[str, Any]], systems: list[dict[str, Any]]
    ) -> list[MEPConnectivityIssue]:
        """Validate pipe connections and system membership.

        Args:
            pipes: List of pipe dictionaries with 'id', 'connectors', 'system_id'
            systems: List of MEP system dictionaries

        Returns:
            List of connectivity issues
        """
        issues = []
        system_map = {sys["id"]: sys for sys in systems}

        for pipe in pipes:
            # Check system membership
            if not pipe.get("system_id"):
                issue = MEPConnectivityIssue(
                    element_id=pipe["id"],
                    element_type="pipe",
                    issue_type="no_system",
                    description="Pipe is not part of any MEP system",
                )
                issues.append(issue)
                self.issues.append(issue)
                continue

            if pipe["system_id"] not in system_map:
                issue = MEPConnectivityIssue(
                    element_id=pipe["id"],
                    element_type="pipe",
                    issue_type="invalid_system",
                    description=f"Pipe references invalid system ID: {pipe['system_id']}",
                )
                issues.append(issue)
                self.issues.append(issue)
                continue

            # Check connectors
            connectors = pipe.get("connectors", [])
            disconnected = [c for c in connectors if not c.get("connected")]

            if len(disconnected) > 1:
                issue = MEPConnectivityIssue(
                    element_id=pipe["id"],
                    element_type="pipe",
                    issue_type="multiple_disconnected",
                    description=f"Pipe has {len(disconnected)} disconnected connectors",
                    system_name=system_map[pipe["system_id"]]["name"],
                )
                issues.append(issue)
                self.issues.append(issue)

        return issues

    def validate_system_equipment(
        self, equipment: list[dict[str, Any]], systems: list[dict[str, Any]]
    ) -> list[MEPConnectivityIssue]:
        """Validate MEP equipment connections to systems.

        Args:
            equipment: List of equipment dictionaries (air terminals, fixtures, etc.)
            systems: List of MEP systems

        Returns:
            List of connectivity issues
        """
        issues = []
        system_map = {sys["id"]: sys for sys in systems}

        for equip in equipment:
            # Equipment must belong to a system
            if not equip.get("system_id"):
                issue = MEPConnectivityIssue(
                    element_id=equip["id"],
                    element_type=equip.get("type", "equipment"),
                    issue_type="no_system",
                    description=f"{equip.get('type', 'Equipment')} is not connected to any system",
                )
                issues.append(issue)
                self.issues.append(issue)
                continue

            # Verify system exists
            if equip["system_id"] not in system_map:
                issue = MEPConnectivityIssue(
                    element_id=equip["id"],
                    element_type=equip.get("type", "equipment"),
                    issue_type="invalid_system",
                    description=f"{equip.get('type', 'Equipment')} references invalid system",
                )
                issues.append(issue)
                self.issues.append(issue)

        return issues

    def find_isolated_elements(
        self, elements: list[dict[str, Any]]
    ) -> list[MEPConnectivityIssue]:
        """Find MEP elements that are isolated (no connections).

        Args:
            elements: List of MEP element dictionaries with 'id', 'type', 'connectors'

        Returns:
            List of isolated element issues
        """
        issues = []

        for element in elements:
            connectors = element.get("connectors", [])

            if not connectors:
                # Element has no connectors at all
                issue = MEPConnectivityIssue(
                    element_id=element["id"],
                    element_type=element.get("type", "element"),
                    issue_type="no_connectors",
                    description=f"{element.get('type', 'Element')} has no connectors",
                )
                issues.append(issue)
                self.issues.append(issue)
                continue

            # Check if all connectors are disconnected
            all_disconnected = all(not c.get("connected") for c in connectors)

            if all_disconnected:
                issue = MEPConnectivityIssue(
                    element_id=element["id"],
                    element_type=element.get("type", "element"),
                    issue_type="isolated",
                    description=f"{element.get('type', 'Element')} has no connections (isolated)",
                )
                issues.append(issue)
                self.issues.append(issue)

        return issues

    def get_issues(self) -> list[MEPConnectivityIssue]:
        """Get all MEP connectivity issues.

        Returns:
            List of all issues
        """
        return self.issues

    def get_issues_by_type(self, issue_type: str) -> list[MEPConnectivityIssue]:
        """Get issues of a specific type.

        Args:
            issue_type: Type of issue to filter by

        Returns:
            List of issues of that type
        """
        return [issue for issue in self.issues if issue.issue_type == issue_type]

    def get_issues_by_system(self, system_name: str) -> list[MEPConnectivityIssue]:
        """Get issues for a specific system.

        Args:
            system_name: Name of the system

        Returns:
            List of issues for that system
        """
        return [issue for issue in self.issues if issue.system_name == system_name]

    def clear_issues(self) -> None:
        """Clear all recorded issues."""
        self.issues = []

    def get_issue_count(self) -> int:
        """Get total number of issues.

        Returns:
            Count of issues
        """
        return len(self.issues)
