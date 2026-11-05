<?php
/** Render the small Markdown subset used by the versioned store policies. */
function wrag_seed_markdown( $source ) {
	// The policy files place paragraphs directly below headings.
	$source = preg_replace( '/^(#{1,2} [^\r\n]+)\R/m', '$1' . "\n\n", trim( $source ) );
	$blocks = preg_split( '/\R\s*\R/', trim( $source ) );
	$html = array();
	foreach ( $blocks as $block ) {
		$block = htmlspecialchars( $block, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8' );
		$block = preg_replace( '/\*\*(.+?)\*\*/s', '<strong>$1</strong>', $block );
		if ( preg_match( '/^# [^\r\n]+$/', $block ) ) {
			continue; // WordPress already renders the page title.
		}
		if ( preg_match( '/^## ([^\r\n]+)$/', $block, $match ) ) {
			$html[] = '<h2>' . $match[1] . '</h2>';
		} elseif ( preg_match( '/^(?:- |\d+\. )/', $block ) ) {
			$tag = str_starts_with( $block, '- ' ) ? 'ul' : 'ol';
			$items = preg_replace( '/^(?:- |\d+\. )(.+)$/m', '<li>$1</li>', $block );
			$html[] = '<' . $tag . '>' . $items . '</' . $tag . '>';
		} else {
			$html[] = '<p>' . $block . '</p>';
		}
	}
	// shortcut: headings, paragraphs, lists and bold only; extend when seed docs need more syntax.
	return implode( "\n", $html );
}
