all:
	tinker --build
	find blog \( -name \*.eot.gz -o -name \*.svg.gz -o -name \*.ttf.gz -o -name \*.woff.gz -o -name \*.html.gz -o -name \*.css.gz -o -name \*.js.gz \) -print -delete
	find blog \( -name \*.eot -o -name \*.svg -o -name \*.ttf -o -name \*.woff -o -name \*.html -o -name \*.css -o -name \*.js \) -print -exec gzip -9 -k '{}' \;
