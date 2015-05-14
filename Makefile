all:
	tinker --build
	find blog \( -name \*.html.gz -o -name \*.css.gz -o -name \*.js.gz \) -print -delete
	find blog \( -name \*.html -o -name \*.css -o -name \*.js \) -exec gzip -9 -k '{}' \;
	
