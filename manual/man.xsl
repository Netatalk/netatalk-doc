<?xml version='1.0'?> 
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0"> 
<xsl:import href="PATH_TO_XSL_STYLESHEETS_DIR/manpages/docbook.xsl"/> 

<!-- * Suppress extra :VERSION: -->
<xsl:param name="refentry.version.suppress">1</xsl:param>

<!-- * Example without numbering -->
<xsl:param name="local.l10n.xml" select="document('')"/>
<l:i18n xmlns:l="http://docbook.sourceforge.net/xmlns/l10n/1.0">
<l:l10n language="en">
 <l:context name="title">
    <l:template name="example" text="Example.&#160;%t"/>
 </l:context>
 <l:context name="title-numbered">
    <l:template name="example" text="Example.&#160;%t"/>
 </l:context>
</l:l10n>
</l:i18n>

<!-- * The default XSL stylesheet insert groff code that nroff can't parse -->
<xsl:template name="define.macros">
	<xsl:text>.\" -----------------------------------------------------------------&#10;</xsl:text>
	<xsl:text>.\" * (re)Define some macros&#10;</xsl:text>
    <xsl:text>.\" -----------------------------------------------------------------&#10;</xsl:text>
    <xsl:text>.\" ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~&#10;</xsl:text>
    <xsl:text>.\" BB/BE - put background/screen (filled box) around block of text&#10;</xsl:text>
    <xsl:text>.\" ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~&#10;</xsl:text>
    <xsl:text>.de BB
.if t \{\
.sp -.5
.br
.in +2n
.ll -2n
.gcolor red
.di BX
.\}
..
.de EB
.if t \{\
.if "\\$2"adjust-for-leading-newline" \{\
.sp -1
.\}
.br
.di
.in
.ll
.gcolor
.nr BW \\n(.lu-\\n(.i
.nr BH \\n(dn+.5v
.ne \\n(BHu+.5v
.ie "\\$2"adjust-for-leading-newline" \{\
\M[\\$1]\h'1n'\v'+.5v'\D'P \\n(BWu 0 0 \\n(BHu -\\n(BWu 0 0 -\\n(BHu'\M[]
.\}
.el \{\
\M[\\$1]\h'1n'\v'-.5v'\D'P \\n(BWu 0 0 \\n(BHu -\\n(BWu 0 0 -\\n(BHu'\M[]
.\}
.in 0
.sp -.5v
.nf
.BX
.in
.sp .5v
.fi
.\}
..&#10;</xsl:text>
	<xsl:text>.\" ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~&#10;</xsl:text>
	<xsl:text>.\" BM/EM - put colored marker in margin next to block of text&#10;</xsl:text>
	<xsl:text>.\" ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~&#10;</xsl:text>
	<xsl:text>.de BM
.if t \{\
.br
.ll -2n
.gcolor red
.di BX
.\}
..
.de EM
.if t \{\
.br
.di
.ll
.gcolor
.nr BH \\n(dn
.ne \\n(BHu
\M[\\$1]\D'P -.75n 0 0 \\n(BHu -(\\n[.i]u - \\n(INu - .75n) 0 0 -\\n(BHu'\M[]
.in 0
.nf
.BX
.in
.fi
.\}
..&#10;</xsl:text>
</xsl:template>


</xsl:stylesheet>
