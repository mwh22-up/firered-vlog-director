import unittest

from vlog_director.audio_qa import parse_ebur128, parse_silences, parse_volume


class AudioQATests(unittest.TestCase):
    def test_parse_ebur128_uses_final_summary(self) -> None:
        output = """
        I: -20.0 LUFS
        Peak: -2.0 dBFS
        I: -16.1 LUFS
        Peak: -1.4 dBFS
        """
        self.assertEqual(
            parse_ebur128(output),
            {"integrated_lufs": -16.1, "true_peak_dbfs": -1.4},
        )

    def test_parse_silence_and_volume(self) -> None:
        silence = "silence_start: 2.5\nsilence_end: 5.0 | silence_duration: 2.5"
        self.assertEqual(
            parse_silences(silence),
            [{"start_sec": 2.5, "end_sec": 5.0, "duration_sec": 2.5}],
        )
        self.assertEqual(
            parse_volume("mean_volume: -22.4 dB\nmax_volume: -3.1 dB"),
            {"mean_db": -22.4, "max_db": -3.1},
        )


if __name__ == "__main__":
    unittest.main()
