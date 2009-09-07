
VPATH = manual/man/man1:manual/man/man3:manual/man/man4:manual/man/man5:manual/man/man8

man1pages = manpages/achfile.1 \
		manpages/ad.1 \
		manpages/aecho.1 \
		manpages/afile.1 \
		manpages/afppasswd.1 \
		manpages/apple_cleanup.1 \
		manpages/apple_cp.1 \
		manpages/apple_mv.1 \
		manpages/apple_rm.1 \
		manpages/asip-status.pl.1 \
		manpages/dbd.1 \
		manpages/getzones.1 \
		manpages/megatron.1 \
		manpages/nbp.1 \
		manpages/netatalk-config.1 \
		manpages/pap.1 \
		manpages/psorder.1  \
		manpages/uniconv.1

man3pages = manpages/atalk_aton.3 \
		manpages/nbp_name.3

man4pages = manpages/atalk.4

man5pages = manpages/afpd.conf.5  \
		manpages/afp_ldap.conf.5 \
		manpages/papd.conf.5 \
		manpages/AppleVolumes.default.5 \
		manpages/atalkd.conf.5 \
		manpages/netatalk.conf.5

man8pages = manpages/afp_acls.8 \
		manpages/afpd.8 \
		manpages/atalkd.8 \
		manpages/cnid_dbd.8 \
		manpages/cnid_metad.8 \
		manpages/papd.8 \
		manpages/papstatus.8 \
		manpages/psf.8 \
		manpages/timelord.8

manpages/%.1 : %.1.xml
		@xsltproc -o manpages/ manual/man.xsl $<
		@sed -i -e "s@:NETATALK_VERSION:@Netatalk $(VERSION)@g" $@

manpages/%.3 : %.3.xml
		@xsltproc -o manpages/ manual/man.xsl $< 
		@sed -i -e "s@:NETATALK_VERSION:@Netatalk $(VERSION)@g" $@

manpages/%.4 : %.4.xml
		@xsltproc -o manpages/ manual/man.xsl $< 
		@sed -i -e "s@:NETATALK_VERSION:@Netatalk $(VERSION)@g" $@

manpages/%.5 : %.5.xml
		@xsltproc -o manpages/ manual/man.xsl $< 
		@sed -i -e "s@:NETATALK_VERSION:@Netatalk $(VERSION)@g" $@

manpages/%.8 : %.8.xml
		@xsltproc -o manpages/ manual/man.xsl $< 
		@sed -i -e "s@:NETATALK_VERSION:@Netatalk $(VERSION)@g" $@

.PHONY:	all manpageinit clean install
all:	man

man:	manpageinit $(man1pages) $(man3pages) $(man4pages) $(man5pages) $(man8pages)

manpageinit:
		@if [ "x$(XSL)" = "x" ] ; then \
			echo 'Set $$XSL to be the path of your XSL stylesheet directory.'; \
			exit 1; \
		fi
		@if [ "x$(VERSION)" = "x" ] ; then \
			echo 'Set $$VERSION to the Netatalk version'; \
			exit 1; \
		fi
		@echo Configuring XSL stylesheet with path $(XSL)
		@sed -i -e "s@PATH_TO_XSL_STYLESHEETS_DIR@$(XSL)@" manual/man.xsl
		@if [ ! -d manpages ] ; then \
			mkdir manpages; \
		fi

clean:
		rm -f manpages/*

install:
		@if [ "x$(DIR)" = "x" ] ; then \
			echo 'Set $$DIR to be the path of your Netatalk directory.'; \
			exit 1; \
		fi
		sh manual/checkinmans "$(DIR)"
