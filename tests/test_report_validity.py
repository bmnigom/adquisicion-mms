import math
import unittest

from core.kinematics import Metric
from core.report import ReportContext, measurement_verdict, render_html


class ReportValidityTests(unittest.TestCase):
    def context(self, value, duration=1.0):
        return ReportContext("jump", "Salto", "Cadera", "01", "01", duration,
                             [Metric("height", "Altura", value, "cm")], [])

    def test_nonfinite_metric_is_consistently_rejected_and_explained(self):
        for value in (float("nan"), float("inf"), None):
            with self.subTest(value=value):
                context = self.context(value)
                self.assertEqual(measurement_verdict(context)[0], "fail")
                html = render_html(context)
                self.assertIn("Resultados numéricos", html)
                self.assertNotIn("nan", html.lower())

    def test_nonfinite_duration_is_a_quality_failure(self):
        context = self.context(30.0, math.inf)
        self.assertEqual(measurement_verdict(context)[0], "fail")
        self.assertIn("duración", render_html(context))


if __name__ == "__main__":
    unittest.main()
