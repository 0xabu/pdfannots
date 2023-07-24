from pathlib import Path
import uuid
import json
import typing as typ

from . import Printer
from ..types import Annotation, Document


def annot_to_dict(
    doc: Document,
    annot: Annotation,
    remove_hyphens: bool
) -> typ.Dict[str, typ.Any]:
    """Convert an annotation to a dictionary representation suitable for JSON encoding."""
    assert annot.pos

    result = {
        "id #uuid": str(uuid.uuid4()),
        "page": annot.pos.page.pageno + 1,
    }

    if annot.boxes:
        bd_x1 = min([b.x0 for b in annot.boxes])
        bd_y1 = min([b.y0 for b in annot.boxes])
        bd_x2 = max([b.x1 for b in annot.boxes])
        bd_y2 = max([b.y1 for b in annot.boxes])
        bd_w = int(bd_x2 - bd_x1)
        bd_h = int(bd_y2 - bd_y1)
        result['position'] = {
            "bounding": {
                "x1": bd_x1,
                "y1": bd_y1,
                "x2": bd_x2,
                "y2": bd_y2,
                "width": bd_w,
                "height": bd_h,
            },
            "rects": [
                {
                    "x1": b.x0,
                    "x2": b.x1,
                    "y1": b.y0,
                    "y2": b.y1,
                    "width": b.get_width(),
                    "height": b.get_height(),
                }
                for b in annot.boxes
            ],
            "page": result["page"],
        }


    if annot.text:
        result['content'] = {
                "text": annot.gettext(remove_hyphens)
                }

    result["properties"] = {"color": "yellow"}

    return result

def idt(n):
    "simple indenter"
    return "\t" * n

def edn_var_formatter(text, var):
    return text.replace(f'"{var}": ', f':{var} ')


class EDNPrinter(Printer):
    def __init__(self, *, remove_hyphens: bool) -> None:
        self.remove_hyphens = remove_hyphens  # Whether to remove hyphens across a line break
        self.seen_first = False

    def end(self) -> str:
        return '\n'

    def print_file(
        self,
        filename: str,
        document: Document
    ) -> typ.Iterator[str]:
        if self.seen_first:
            # The flat array format is incompatible with multiple input files
            # TODO: Ideally we'd catch this at invocation time
            raise RuntimeError("The Logseq output format does not support multiple files.")
        else:
            self.seen_first = True

        annots = {
                "highlights": [annot_to_dict(document, a, self.remove_hyphens) for a in document.iter_annots()]
                }

        # create the md file alongside the annotations 
        md = "file-path:: ../assets/" + Path(filename).name + "\n\n"
        for an in annots["highlights"]:
            md += "- " + an["content"]["text"] + "\n"
            md += "  ls-type:: annotation\n"
            md += "  hl-page:: " + str(an["page"]) + "\n"
            md += "  hl-color:: yellow\n"
            md += "  id:: " + an["id #uuid"] + "\n"


        edn = json.dumps(annots, indent=2)

        for var in ["x1", "y1", "x2", "y2", "width", "height", "id #uuid",
                "page", "position", "content", "text", "properties",
                "color", "rects", "bounding", "highlights"]:
            edn = edn_var_formatter(edn, var)

        return {
                "markdown_part": md,
                "edn_part": edn,
            }
