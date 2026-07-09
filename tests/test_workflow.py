from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


class TestWorkflow:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_execute_workflow_success(self):
        wf = self.manager.create_workflow("wf")
        wf.add_step(WorkflowStep("one", lambda: 1))
        wf.add_step(WorkflowStep("two", lambda: 2))
        assert self.manager.execute_workflow(wf.id)
        assert wf.status == StepStatus.COMPLETED
        assert [s.result for s in wf.steps] == [1, 2]

    def test_execute_workflow_failure_stops(self):
        wf = self.manager.create_workflow("wf")

        def boom():
            raise ValueError("bad step")

        wf.add_step(WorkflowStep("boom", boom))
        never_ran = WorkflowStep("after", lambda: 3)
        wf.add_step(never_ran)

        assert not self.manager.execute_workflow(wf.id)
        assert wf.status == StepStatus.FAILED
        assert wf.steps[0].error == "bad step"
        assert never_ran.status == StepStatus.PENDING

    def test_step_retries_until_success(self):
        wf = self.manager.create_workflow("wf")
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("flaky")
            return "ok"

        wf.add_step(WorkflowStep("flaky", flaky, retries=2))
        assert self.manager.execute_workflow(wf.id)
        assert calls["n"] == 3
        assert wf.steps[0].result == "ok"
        assert wf.steps[0].error is None
