PENPATH ?= python -m penpath
IMAGE := circle.png
SVG := circle.svg
GCODE := circle.gcode
PREVIEWS := circle.svg.png circle.gcode.png

.PHONY: all clean previews

all: $(SVG) $(GCODE) $(PREVIEWS)

$(SVG): $(IMAGE)
	$(PENPATH) convert $(IMAGE) -o $(SVG) --paper 170x170,10 -s seed=42 --quiet

$(GCODE): $(SVG)
	$(PENPATH) gcode $(SVG) --profile aquila -o $(GCODE)

previews: $(PREVIEWS)

%.svg.png: %.svg
	$(PENPATH) preview $< -o $@

%.gcode.png: %.gcode
	$(PENPATH) preview $< -o $@

clean:
	rm -f $(SVG) $(GCODE) $(PREVIEWS)
