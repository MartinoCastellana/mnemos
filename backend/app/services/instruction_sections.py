import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstructionSections:
    """Runtime views of the authoritative instruction file.

    The source text is never rewritten: each pipeline phase receives only the
    numbered sections it needs, copied verbatim from the same file.
    """

    source: str
    sections: dict[str, str]
    preamble: str

    @classmethod
    def parse(cls, source: str) -> "InstructionSections":
        # Top-level headings end with a dot ("19. ..."), while the authoritative
        # document uses dotless nested headings ("19.4 COMUNE"). Parse both forms.
        matches = list(re.finditer(r"(?m)^(\d+(?:\.\d+)*)(?:\.)?\s+[^\n]+$", source))
        sections: dict[str, str] = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
            sections[match.group(1)] = source[match.start() : end].strip()
        preamble = source[: matches[0].start()].strip() if matches else ""
        return cls(source=source, sections=sections, preamble=preamble)

    def select(self, *numbers: str) -> str:
        selected = [self.preamble] if self.preamble else []
        selected.extend(self.sections[number] for number in numbers if number in self.sections)
        return "\n\n".join(selected)

    def page_analysis(self) -> str:
        field_rules = tuple(f"19.{number}" for number in range(1, 17))
        return self.select(
            "1", "2", "5", "6", "7", "8", "9", "10", "14", "15", *field_rules
        )

    def protocol_page(self) -> str:
        return self.select("1", "6", "7", "8", "9", "10", "19.1", "19.2")

    def protocol_global(self) -> str:
        return self.select("1", "16", "17", "18", "19", "19.1", "19.2", "20", "21", "22")

    def global_resolution(self) -> str:
        field_rules = tuple(f"19.{number}" for number in range(1, 17))
        return self.select("1", "16", "17", "18", "19", *field_rules, "20", "21", "22")
